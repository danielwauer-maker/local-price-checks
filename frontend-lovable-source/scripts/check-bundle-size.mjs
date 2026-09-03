import { gzipSync } from "node:zlib";
import { readdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const assetsDirectory = fileURLToPath(new URL("../.output/public/assets/", import.meta.url));
const files = await readdir(assetsDirectory);
const entryFiles = files.filter((name) => /^index-[\w-]+\.js$/.test(name));

if (entryFiles.length !== 1) {
  throw new Error(`Expected one client entry chunk, found ${entryFiles.length}.`);
}

const entryFile = entryFiles[0];
const bytes = gzipSync(await readFile(join(assetsDirectory, entryFile))).byteLength;
const limit = 105 * 1024;
const formatted = (value) => `${(value / 1024).toFixed(2)} KiB gzip`;

console.log(`Client entry ${entryFile}: ${formatted(bytes)} (limit ${formatted(limit)})`);
if (bytes > limit) {
  throw new Error("Client entry bundle exceeded the performance budget.");
}
