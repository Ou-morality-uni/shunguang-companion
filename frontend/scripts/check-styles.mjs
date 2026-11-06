import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const postcss = createRequire(import.meta.resolve('vite'))('postcss');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../src');
const issues = [];
const tokens = new Map();
function inspect(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) inspect(file);
    else if (file.endsWith('.css')) {
      const ast = postcss.parse(fs.readFileSync(file, 'utf8'), { from: file });
      ast.walkDecls((declaration) => {
        if (file.endsWith(path.join('styles', 'tokens.css'))) {
          tokens.set(declaration.prop, declaration.value);
          return;
        }
        if (/#[\da-f]{3,8}\b|\b(?:rgba?|hsla?|oklch)\(/i.test(declaration.value))
          issues.push(
            `${path.relative(root, file)}:${declaration.source.start.line}: use a semantic color token`,
          );
        if (
          declaration.prop === 'font-size' &&
          [...declaration.value.matchAll(/([\d.]+)px/g)].some((match) => +match[1] < 12)
        )
          issues.push(
            `${path.relative(root, file)}:${declaration.source.start.line}: information text must be at least 12px`,
          );
      });
    }
  }
}
inspect(root);
function luminance(hex) {
  const values = [1, 3, 5]
    .map((index) => parseInt(hex.slice(index, index + 2), 16) / 255)
    .map((value) => (value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4));
  return values.reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
}
for (const text of ['primary', 'secondary', 'muted', 'dim']) {
  for (const surface of ['deep', 'base', 'panel', 'raised']) {
    const contrast =
      (luminance(tokens.get(`--tone-text-${text}`)) + 0.05) /
      (luminance(tokens.get(`--tone-surface-${surface}`)) + 0.05);
    if (contrast < 4.5) issues.push(`text-${text} on surface-${surface}: ${contrast.toFixed(2)} < 4.5`);
  }
}
if (issues.length) {
  process.stderr.write(issues.join('\n') + '\n');
  process.exit(1);
}
process.stdout.write(
  'Semantic colors, minimum font sizes and primary text palette contrast passed. Browser compositing still requires visual QA.\n',
);
