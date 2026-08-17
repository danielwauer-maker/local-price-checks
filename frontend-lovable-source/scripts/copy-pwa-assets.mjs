import { cp, mkdir, readdir } from "node:fs/promises";
import { join } from "node:path";

const sourceDir = "dist";
const targetDir = ".output/public";

await mkdir(targetDir, { recursive: true });

const files = await readdir(sourceDir);

for (const file of files) {
  if (file === "sw.js" || /^workbox-.*\.js$/.test(file)) {
    await cp(join(sourceDir, file), join(targetDir, file));
    console.log(`[PWA] Copied ${file} -> ${targetDir}`);
  }
}