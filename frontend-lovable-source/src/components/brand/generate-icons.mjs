import { deflateSync, inflateSync } from "node:zlib";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(here, "../../../public/brand");
const canonicalPath = resolve(outDir, "spareno-icon-512.png");

if (!existsSync(canonicalPath)) {
  throw new Error("missing canonical Spareno asset: spareno-icon-512.png");
}

const crcTable = new Uint32Array(256);
for (let n = 0; n < 256; n++) {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  crcTable[n] = c >>> 0;
}

function crc32(buf) {
  let c = 0xffffffff;
  for (const b of buf) c = crcTable[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const typeBuf = Buffer.from(type);
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0);
  return Buffer.concat([len, typeBuf, data, crc]);
}

function paeth(a, b, c) {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  if (pa <= pb && pa <= pc) return a;
  if (pb <= pc) return b;
  return c;
}

function decodePng(buffer) {
  const signature = buffer.subarray(0, 8);
  const expected = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  if (!signature.equals(expected)) throw new Error("canonical Spareno asset is not a PNG");

  let offset = 8;
  let width = 0;
  let height = 0;
  let bitDepth = 0;
  let colorType = 0;
  let interlace = 0;
  let palette = null;
  let transparency = null;
  const idat = [];

  while (offset < buffer.length) {
    const length = buffer.readUInt32BE(offset);
    const type = buffer.toString("ascii", offset + 4, offset + 8);
    const data = buffer.subarray(offset + 8, offset + 8 + length);
    offset += 12 + length;

    if (type === "IHDR") {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      bitDepth = data[8];
      colorType = data[9];
      interlace = data[12];
    } else if (type === "PLTE") {
      palette = data;
    } else if (type === "tRNS") {
      transparency = data;
    } else if (type === "IDAT") {
      idat.push(data);
    } else if (type === "IEND") {
      break;
    }
  }

  if (bitDepth !== 8 || interlace !== 0 || ![3, 6].includes(colorType)) {
    throw new Error(
      `unsupported canonical PNG format: bitDepth=${bitDepth}, colorType=${colorType}, interlace=${interlace}`,
    );
  }
  if (colorType === 3 && !palette) throw new Error("indexed canonical PNG is missing its palette");

  const bytesPerPixel = colorType === 6 ? 4 : 1;
  const stride = width * bytesPerPixel;
  const raw = inflateSync(Buffer.concat(idat));
  const expectedLength = (stride + 1) * height;
  if (raw.length !== expectedLength) {
    throw new Error(`unexpected decoded PNG length: ${raw.length}; expected ${expectedLength}`);
  }

  const scanline = Buffer.alloc(stride * height);
  let srcOffset = 0;

  for (let y = 0; y < height; y++) {
    const filter = raw[srcOffset++];
    if (filter > 4) throw new Error(`unsupported PNG filter: ${filter} on row ${y}`);
    const rowStart = y * stride;

    for (let x = 0; x < stride; x++) {
      const value = raw[srcOffset++];
      const left = x >= bytesPerPixel ? scanline[rowStart + x - bytesPerPixel] : 0;
      const up = y > 0 ? scanline[rowStart - stride + x] : 0;
      const upLeft =
        x >= bytesPerPixel && y > 0 ? scanline[rowStart - stride + x - bytesPerPixel] : 0;

      let decoded;
      if (filter === 0) decoded = value;
      else if (filter === 1) decoded = (value + left) & 0xff;
      else if (filter === 2) decoded = (value + up) & 0xff;
      else if (filter === 3) decoded = (value + Math.floor((left + up) / 2)) & 0xff;
      else decoded = (value + paeth(left, up, upLeft)) & 0xff;

      scanline[rowStart + x] = decoded;
    }
  }

  if (colorType === 6) return { width, height, rgba: scanline };

  const rgba = Buffer.alloc(width * height * 4);
  for (let i = 0; i < width * height; i++) {
    const index = scanline[i];
    const paletteOffset = index * 3;
    const out = i * 4;
    rgba[out] = palette[paletteOffset] ?? 0;
    rgba[out + 1] = palette[paletteOffset + 1] ?? 0;
    rgba[out + 2] = palette[paletteOffset + 2] ?? 0;
    rgba[out + 3] = transparency && index < transparency.length ? transparency[index] : 255;
  }

  return { width, height, rgba };
}

function resizeRgba(source, srcWidth, srcHeight, dstWidth, dstHeight) {
  if (srcWidth === dstWidth && srcHeight === dstHeight) return Buffer.from(source);

  const out = Buffer.alloc(dstWidth * dstHeight * 4);
  for (let y = 0; y < dstHeight; y++) {
    const sy = ((y + 0.5) * srcHeight) / dstHeight - 0.5;
    const y0 = Math.max(0, Math.floor(sy));
    const y1 = Math.min(srcHeight - 1, y0 + 1);
    const fy = Math.max(0, sy - y0);

    for (let x = 0; x < dstWidth; x++) {
      const sx = ((x + 0.5) * srcWidth) / dstWidth - 0.5;
      const x0 = Math.max(0, Math.floor(sx));
      const x1 = Math.min(srcWidth - 1, x0 + 1);
      const fx = Math.max(0, sx - x0);
      const dst = (y * dstWidth + x) * 4;

      for (let c = 0; c < 4; c++) {
        const p00 = source[(y0 * srcWidth + x0) * 4 + c];
        const p10 = source[(y0 * srcWidth + x1) * 4 + c];
        const p01 = source[(y1 * srcWidth + x0) * 4 + c];
        const p11 = source[(y1 * srcWidth + x1) * 4 + c];
        const top = p00 + (p10 - p00) * fx;
        const bottom = p01 + (p11 - p01) * fx;
        out[dst + c] = Math.round(top + (bottom - top) * fy);
      }
    }
  }
  return out;
}

function encodeRgbaPng(width, height, rgba) {
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;
  ihdr[9] = 6;

  const stride = width * 4;
  const raw = Buffer.alloc((stride + 1) * height);
  for (let y = 0; y < height; y++) {
    const row = y * (stride + 1);
    raw[row] = 0;
    rgba.copy(raw, row + 1, y * stride, (y + 1) * stride);
  }

  return Buffer.concat([
    signature,
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

const canonical = decodePng(readFileSync(canonicalPath));
const outputs = [
  ["spareno-icon-512.png", 512],
  ["spareno-icon-192.png", 192],
  ["spareno-maskable-512.png", 512],
  ["apple-touch-icon.png", 180],
  ["favicon-32.png", 32],
];

for (const [name, size] of outputs) {
  const rgba = resizeRgba(canonical.rgba, canonical.width, canonical.height, size, size);
  writeFileSync(resolve(outDir, name), encodeRgbaPng(size, size, rgba));
  console.log(`normalized canonical Spareno asset ${name} (${size}x${size}, RGBA)`);
}
