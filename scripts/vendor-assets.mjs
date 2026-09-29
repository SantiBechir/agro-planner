import { copyFileSync, mkdirSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const target = 'core/static/core/vendor';
mkdirSync(target, { recursive: true });
for (const [packageName, source, destination] of [
  ['alpinejs', 'dist/cdn.min.js', 'alpine-3.17.4.min.js'],
  ['chart.js', 'dist/chart.umd.min.js', 'chart-4.5.1.min.js'],
  ['htmx.org', 'dist/htmx.min.js', 'htmx-1.9.12.min.js'],
]) {
  const root = join('node_modules', packageName);
  // ManifestStaticFilesStorage validates source-map references. Maps are not
  // deployed, so strip only the vendor sourceMappingURL comment.
  const script = readFileSync(join(root, source), 'utf8').replace(/\/\/[#@]\s*sourceMappingURL=.*$/gm, '').trimEnd() + '\n';
  writeFileSync(join(target, destination), script);
  const license = ['LICENSE', 'LICENSE.md', 'LICENSE.txt'].find(name => existsSync(join(root, name)));
  const licensePath = license ? join(root, license) : join('assets/licenses', `${packageName}-LICENSE.txt`);
  if (!existsSync(licensePath)) throw new Error(`Missing license for ${packageName}`);
  copyFileSync(licensePath, join(target, `${packageName}-LICENSE.txt`));
}
