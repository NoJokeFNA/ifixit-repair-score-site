import {copyFileSync, mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const copy = (source, target) => copyFileSync(path.join(root, source), path.join(root, target));
mkdirSync(path.join(root, 'assets/vendor'), {recursive: true});
mkdirSync(path.join(root, 'assets/fonts'), {recursive: true});
copy('node_modules/chart.js/dist/chart.umd.min.js', 'assets/vendor/chart.umd.min.js');
copy('node_modules/chart.js/LICENSE.md', 'assets/vendor/chart.LICENSE.md');
const fontPackage = 'node_modules/@fontsource-variable/jetbrains-mono';
const css = readFileSync(path.join(root, fontPackage, 'index.css'), 'utf8')
    .replaceAll('JetBrains Mono Variable', 'JetBrains Mono')
    .replaceAll('./files/', './');
for (const match of css.matchAll(/url\(\.\/([^)]*)\)/g)) {
    copy(`${fontPackage}/files/${match[1]}`, `assets/fonts/${match[1]}`);
}
writeFileSync(path.join(root, 'assets/fonts/fonts.css'), css);
copy(`${fontPackage}/LICENSE`, 'assets/fonts/OFL.txt');
