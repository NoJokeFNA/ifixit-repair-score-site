import {copyFileSync, mkdirSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const copy = (source, target) => copyFileSync(path.join(root, source), path.join(root, target));
mkdirSync(path.join(root, 'assets/licenses'), {recursive: true});
copy('css/site.css', 'styles.css');
copy('node_modules/lucide/dist/umd/lucide.min.js', 'assets/icons.js');
copy('node_modules/lucide/LICENSE', 'assets/licenses/lucide.LICENSE');
copy('node_modules/@fontsource-variable/jetbrains-mono/files/jetbrains-mono-latin-wght-normal.woff2', 'assets/mono.woff2');
copy('node_modules/@fontsource-variable/jetbrains-mono/LICENSE', 'assets/licenses/jetbrains-mono.OFL.txt');
