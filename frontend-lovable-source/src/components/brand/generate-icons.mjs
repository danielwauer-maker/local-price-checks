import { deflateSync } from "node:zlib";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(here, "../../../public/brand");
mkdirSync(outDir, { recursive: true });

const crcTable = new Uint32Array(256);
for (let n = 0; n < 256; n++) {
  let c = n;
  for (let k = 0; k < 8; k++) c = (c & 1) ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
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

function png(width, height, rgba) {
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

function hex(s) {
  const v = s.replace("#", "");
  return [parseInt(v.slice(0, 2), 16), parseInt(v.slice(2, 4), 16), parseInt(v.slice(4, 6), 16), 255];
}

const NAVY_A = hex("#123A7A");
const NAVY_B = hex("#081E4A");
const NAVY = hex("#102A6E");
const CYAN = hex("#20C9E8");
const GREEN = hex("#22C55E");
const MINT = hex("#A7F3D0");
const WHITE = [255, 255, 255, 255];

function mix(a, b, t) {
  return [
    Math.round(a[0] + (b[0] - a[0]) * t),
    Math.round(a[1] + (b[1] - a[1]) * t),
    Math.round(a[2] + (b[2] - a[2]) * t),
    255,
  ];
}

function render(size, { maskable = false } = {}) {
  const ss = size >= 180 ? 2 : 4;
  const W = size * ss;
  const H = W;
  const data = Buffer.alloc(W * H * 4);
  const px = (x, y, color) => {
    if (x < 0 || y < 0 || x >= W || y >= H) return;
    const i = (y * W + x) * 4;
    data[i] = color[0]; data[i + 1] = color[1]; data[i + 2] = color[2]; data[i + 3] = color[3] ?? 255;
  };
  const fillCircle = (cx, cy, r, color) => {
    const x0 = Math.floor(cx - r), x1 = Math.ceil(cx + r), y0 = Math.floor(cy - r), y1 = Math.ceil(cy + r);
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) if ((x - cx) ** 2 + (y - cy) ** 2 <= r * r) px(x, y, color);
  };
  const line = (x1, y1, x2, y2, w, color) => {
    const dx = x2 - x1, dy = y2 - y1, len2 = dx * dx + dy * dy;
    const minX = Math.floor(Math.min(x1, x2) - w), maxX = Math.ceil(Math.max(x1, x2) + w);
    const minY = Math.floor(Math.min(y1, y2) - w), maxY = Math.ceil(Math.max(y1, y2) + w);
    for (let y = minY; y <= maxY; y++) for (let x = minX; x <= maxX; x++) {
      const t = Math.max(0, Math.min(1, ((x - x1) * dx + (y - y1) * dy) / len2));
      const qx = x1 + t * dx, qy = y1 + t * dy;
      if ((x - qx) ** 2 + (y - qy) ** 2 <= (w / 2) ** 2) px(x, y, color);
    }
  };
  const strokeArc = (cx, cy, r, a1, a2, w, c1, c2) => {
    const steps = Math.ceil(r * Math.abs(a2 - a1) * 1.4);
    for (let i = 0; i <= steps; i++) {
      const t = i / steps, a = a1 + (a2 - a1) * t;
      fillCircle(cx + Math.cos(a) * r, cy + Math.sin(a) * r, w / 2, mix(c1, c2, t));
    }
  };

  for (let y = 0; y < H; y++) {
    const t = y / (H - 1);
    const c = mix(NAVY_A, NAVY_B, t);
    for (let x = 0; x < W; x++) px(x, y, c);
  }

  const safe = maskable ? 0.78 : 0.90;
  const s = W * safe / 64;
  const ox = (W - 64 * s) / 2;
  const oy = ox;
  const X = (v) => ox + v * s;
  const Y = (v) => oy + v * s;
  const S = (v) => v * s;

  strokeArc(X(32), Y(32), S(23.5), Math.PI * 0.77, Math.PI * 1.78, S(2.6), CYAN, GREEN);
  strokeArc(X(32), Y(32), S(19), Math.PI * 1.15, Math.PI * 2.18, S(2.6), CYAN, GREEN);
  strokeArc(X(32), Y(32), S(14), Math.PI * 0.72, Math.PI * 1.83, S(2.6), CYAN, GREEN);
  fillCircle(X(48.4), Y(18), S(2.7), GREEN);

  const pinTop = Y(25), pinBottom = Y(51.5), pinCx = X(32);
  for (let y = Math.floor(pinTop); y <= pinBottom; y++) {
    const t = (y - pinTop) / (pinBottom - pinTop);
    const half = t < 0.55 ? S(8.8) * Math.sqrt(Math.max(0, 1 - ((t - 0.28) / 0.34) ** 2)) : S(8.8) * (1 - (t - 0.55) / 0.45);
    const c = mix(MINT, GREEN, t);
    for (let x = Math.floor(pinCx - half); x <= Math.ceil(pinCx + half); x++) px(x, y, c);
  }

  fillCircle(X(32), Y(34.6), S(9.1), WHITE);
  line(X(27.7), Y(39), X(36.4), Y(30.3), S(2.2), NAVY);
  fillCircle(X(27.6), Y(30.6), S(2.2), NAVY);
  fillCircle(X(27.6), Y(30.6), S(0.75), WHITE);
  fillCircle(X(36.6), Y(39), S(2.2), NAVY);
  fillCircle(X(36.6), Y(39), S(0.75), WHITE);

  if (ss === 1) return data;
  const out = Buffer.alloc(size * size * 4);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const sums = [0, 0, 0, 0];
    for (let yy = 0; yy < ss; yy++) for (let xx = 0; xx < ss; xx++) {
      const i = (((y * ss + yy) * W) + (x * ss + xx)) * 4;
      sums[0] += data[i]; sums[1] += data[i + 1]; sums[2] += data[i + 2]; sums[3] += data[i + 3];
    }
    const o = (y * size + x) * 4, n = ss * ss;
    out[o] = Math.round(sums[0] / n); out[o + 1] = Math.round(sums[1] / n); out[o + 2] = Math.round(sums[2] / n); out[o + 3] = Math.round(sums[3] / n);
  }
  return out;
}

const outputs = [
  ["spareno-icon-512.png", 512, false],
  ["spareno-icon-192.png", 192, false],
  ["spareno-maskable-512.png", 512, true],
  ["apple-touch-icon.png", 180, true],
  ["favicon-32.png", 32, false],
];

for (const [name, size, maskable] of outputs) {
  writeFileSync(resolve(outDir, name), png(size, size, render(size, { maskable })));
  console.log(`generated ${name}`);
}
