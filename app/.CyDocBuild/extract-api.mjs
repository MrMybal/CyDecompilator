// Official CyDoc comment extraction; implementation text never enters the export.
import { extractComments } from 'cydoc/extract';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
const base = dirname(fileURLToPath(import.meta.url));
const source = await readFile(resolve(base, '../documentation.py'), 'utf8');
const pages = extractComments(source, 'documentation.py');
for (const page of pages) {
  if (!['help-route-api','open-help-api'].includes(page.id) || !['en','fr'].includes(page.locale)) throw new Error('Unexpected public help annotation');
  const original = pages.find(p=>p.id===page.id && p.locale==='en');
  const revision = createHash('sha256').update(original.markdown).digest('hex').slice(0,12);
  const description = page.locale==='fr' ? 'Créer et ouvrir des liens locaux validés vers les chapitres de l’aide.' : 'Create and open validated local links to help chapters.';
  const target = resolve(process.argv[2],page.locale,`${page.id}.md`);
  await mkdir(dirname(target),{recursive:true});
  await writeFile(target,`---\nid: ${page.id}\ntitle: ${page.title}\ndescription: ${description}\nsection: ${page.locale==='fr'?'Références / Intégration':'Reference / Integration'}\nparent: help-api\norder: 100\nkind: api\nsymbol: ${page.symbol}\n${page.locale==='fr'?'sourceRevision':'revision'}: ${revision}\n---\n\n${page.markdown}\n`);
}
