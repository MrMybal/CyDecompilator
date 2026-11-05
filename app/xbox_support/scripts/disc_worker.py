"""Job-owned disc extraction worker; stdout is captured by cydec.process.run."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from xbox_support.xbox_native.disc import Disc, prepare, extract_assets


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('destination',type=Path)
    parser.add_argument('--entry',default='')
    parser.add_argument('--max-bytes',type=int,required=True)
    args=parser.parse_args()
    args.destination.mkdir(parents=True,exist_ok=False)
    record=prepare(args.source,args.destination/'probe',args.entry or None)
    image=record.get('disc_image')
    if image:
        with Disc(Path(image)) as disc:
            total=sum(e['size'] for e in disc.entries() if not e['directory'])
            if total>args.max_bytes:raise ValueError('The game exceeds the configured byte limit.')
        extracted=extract_assets(Path(image),args.destination/'game')
        record['extracted_files']=extracted['file_count']
    (args.destination/'worker.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
