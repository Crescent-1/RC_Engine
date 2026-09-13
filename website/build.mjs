import { mkdir, copyFile, access } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = dirname(fileURLToPath(import.meta.url));
const files = ['index.html', 'robots.txt', 'sitemap.xml', 'css/main.css', 'js/app.js', 'assets/favicon.svg', 'assets/apple-touch-icon.png', 'assets/og-image.png'];
try { await access(resolve(root, 'assets/editorial.png')); files.push('assets/editorial.png'); } catch {}
for (const file of files) {
  const target = resolve(root, 'dist', file);
  await mkdir(dirname(target), { recursive: true });
  await copyFile(resolve(root, file), target);
}
console.log(`Prepared ${files.length} public files in website/dist.`);
