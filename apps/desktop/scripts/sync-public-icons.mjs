/** Copy Tauri icons into Vite public/ for favicon + boot splash. */
import { copyFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const icons = join(root, "src-tauri", "icons");
const pub = join(root, "public");
const brand = join(pub, "brand");

mkdirSync(brand, { recursive: true });

const copies = [
  [join(icons, "icon.ico"), join(pub, "favicon.ico")],
  [join(icons, "32x32.png"), join(pub, "favicon-32.png")],
  [join(icons, "128x128.png"), join(pub, "icon-128.png")],
  [join(root, "src", "assets", "brand", "logo.png"), join(brand, "logo.png")],
];

for (const [from, to] of copies) {
  if (!existsSync(from)) {
    console.warn(`skip (missing): ${from}`);
    continue;
  }
  copyFileSync(from, to);
  console.log(`copied ${to}`);
}
