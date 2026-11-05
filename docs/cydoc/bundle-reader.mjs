import { createRequire } from 'node:module';
import { resolve } from 'node:path';
const { build } = createRequire(resolve(process.cwd(), 'package.json'))('esbuild');
const [root, output] = process.argv.slice(2);
await build({entryPoints:[resolve(root,'reader.mjs')],bundle:true,format:'iife',minify:true,target:'es2020',
  nodePaths:[resolve(process.cwd(),'node_modules')],outfile:resolve(output,'viewer.js'),legalComments:'eof'});
