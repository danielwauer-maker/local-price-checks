import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(here, "../../../public/brand");

const required = [
  "spareno-icon-192.png",
  "spareno-icon-512.png",
  "spareno-maskable-512.png",
  "apple-touch-icon.png",
  "favicon-32.png",
];

for (const name of required) {
  const path = resolve(outDir, name);
  if (!existsSync(path)) throw new Error(`missing canonical Spareno asset: ${name}`);
  console.log(`validated canonical asset ${name}`);
}
