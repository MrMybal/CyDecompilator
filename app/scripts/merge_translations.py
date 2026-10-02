"""Merge app/locales/cydec-fr.json into the scaffold catalogue app/locales/ui.json.

ui_common.tr() reads ui.json only. Our own strings live in cydec-fr.json (English key ->
French) so they can be reviewed separately; run this after editing it:

    runtime/python/Scripts/python.exe app/scripts/merge_translations.py
"""
import json
from pathlib import Path

LOCALES = Path(__file__).resolve().parents[1] / 'locales'


def main():
    catalog_path = LOCALES / 'ui.json'
    catalog = json.loads(catalog_path.read_text(encoding='utf-8-sig'))
    ours = json.loads((LOCALES / 'cydec-fr.json').read_text(encoding='utf-8'))
    added = changed = 0
    for english, french in ours.items():
        entry = catalog.get(english)
        if entry is None:
            catalog[english] = {'en': english, 'fr': french}
            added += 1
        elif entry.get('fr') != french:
            entry['fr'] = french
            entry.setdefault('en', english)
            changed += 1
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print('ui.json: %d added, %d updated, %d entries' % (added, changed, len(catalog)))


if __name__ == '__main__':
    main()
