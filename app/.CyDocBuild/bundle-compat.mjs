import { build } from 'esbuild';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
await build({ entryPoints:[resolve(dirname(fileURLToPath(import.meta.url)), 'reader-compat.mjs')], bundle:true,
  format:'iife', target:'es2020', minify:true, outfile:resolve(process.argv[2], 'DocData/compatibility.js') });
