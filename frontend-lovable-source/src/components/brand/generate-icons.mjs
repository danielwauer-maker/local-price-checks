import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(here, "../../../public/brand");
const pngSignature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

const required = [
  ["spareno-icon-512.png", 512],
  ["spareno-icon-192.png", 192],
  ["spareno-maskable-512.png", 512],
  ["apple-touch-icon.png", 180],
  ["favicon-32.png", 32],
];

for (const [name, expectedSize] of required) {
  const path = resolve(outDir, name);
  if (!existsSync(path)) throw new Error(`missing canonical Spareno asset: ${name}`);

  const png = readFileSync(path);
  if (png.length < 33 || !png.subarray(0, 8).equals(pngSignature)) {
    throw new Error(`invalid PNG asset: ${name}`);
  }
  if (png.toString("ascii", 12, 16) !== "IHDR") {
    throw new Error(`missing PNG IHDR: ${name}`);
  }

  const width = png.readUInt32BE(16);
  const height = png.readUInt32BE(20);
  const bitDepth = png[24];
  const colorType = png[25];

  if (width !== expectedSize || height !== expectedSize) {
    throw new Error(`unexpected dimensions for ${name}: ${width}x${height}`);
  }
  if (bitDepth !== 8 || colorType !== 6) {
    throw new Error(`asset ${name} must be 8-bit RGBA PNG; got bitDepth=${bitDepth}, colorType=${colorType}`);
  }

  console.log(`validated canonical Spareno asset ${name} (${width}x${height}, RGBA)`);
}
