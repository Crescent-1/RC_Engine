import { mkdir, copyFile, access, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = dirname(fileURLToPath(import.meta.url));
const measurementId = process.env.GA4_MEASUREMENT_ID?.trim();
if (measurementId && !/^G-[A-Z0-9]+$/.test(measurementId)) {
  throw new Error('GA4_MEASUREMENT_ID must be a GA4 web Measurement ID (G- followed by letters or digits).');
}
if (!measurementId && process.argv.includes('--require-analytics')) {
  throw new Error('GA4_MEASUREMENT_ID is required for an analytics-enabled build.');
}
const files = ['index.html', '_redirects', 'robots.txt', 'sitemap.xml', 'css/main.css', 'js/app.js', 'assets/favicon.svg', 'assets/apple-touch-icon.png', 'assets/og-image.png'];
try { await access(resolve(root, 'assets/editorial.png')); files.push('assets/editorial.png'); } catch {}
for (const file of files) {
  const target = resolve(root, 'dist', file);
  await mkdir(dirname(target), { recursive: true });
  await copyFile(resolve(root, file), target);
}
if (measurementId) {
  const indexPath = resolve(root, 'dist', 'index.html');
  const html = await readFile(indexPath, 'utf8');
  const marker = '<!-- GA4_TAG: build.mjs inserts the configured Google tag here. -->';
  if (!html.includes(marker)) throw new Error('GA4 insertion point is missing from index.html.');
  const tag = `<script async src="https://www.googletagmanager.com/gtag/js?id=${measurementId}"></script>\n  <script>\n    window.dataLayer = window.dataLayer || [];\n    function gtag(){dataLayer.push(arguments);}\n    gtag('js', new Date());\n    gtag('config', '${measurementId}');\n  </script>`;
  await writeFile(indexPath, html.replace(marker, tag));
}
console.log(`Prepared ${files.length} public files in website/dist.`);
