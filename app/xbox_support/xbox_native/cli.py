from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import zipfile

from .formats import FormatError, inspect
from .disc import prepare, write_json


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Xbox native porting research (standalone, no emulation)")
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("inspect", help="Read XBE/XEX2 metadata without executing code")
    a.add_argument("input", type=Path)
    a.add_argument("--output", type=Path)
    a = sub.add_parser("extract-assets", help="Extract all game files from a validated Xbox disc into a new directory")
    a.add_argument("input",type=Path)
    a.add_argument("output",type=Path)
    a = sub.add_parser("prepare", help="Prepare a new workspace from XBE, XEX, folder, ISO or ZIP with one ISO")
    a.add_argument("input", type=Path)
    a.add_argument("output", type=Path)
    a.add_argument("--executable")
    a = sub.add_parser("configure", help="Write a conservative XenonRecomp configuration")
    a.add_argument("workspace", type=Path)
    a.add_argument("--profile", type=Path)
    a = sub.add_parser("translate", help="Run external Xbox 360 static CPU translation")
    a.add_argument("workspace", type=Path)
    a.add_argument("--backend", type=Path, required=True)
    a.add_argument("--context", type=Path, required=True)
    a.add_argument("--timeout", type=int, default=1800)
    a = sub.add_parser("analyse", help="Run external XenonAnalyse jump-table discovery")
    a.add_argument("workspace", type=Path)
    a.add_argument("--backend", type=Path, required=True)
    a.add_argument("--timeout", type=int, default=600)
    a = sub.add_parser("audit", help="Inventory unresolved instructions and branches using mapped-image evidence")
    a.add_argument("workspace", type=Path)
    a = sub.add_parser("export-xbe", help="Export Xbox code/data sections for a future static lifting backend")
    a.add_argument("workspace", type=Path)
    a = sub.add_parser("probe", help="Inspect a mapped Xbox 360 image with the optional local native bridge")
    a.add_argument("workspace", type=Path)
    a.add_argument("--backend", type=Path, required=True)
    a.add_argument("--timeout", type=int, default=120)
    a = sub.add_parser("decompile-xbe", help="Map and decompile original-Xbox XBE through optional Ghidra")
    a.add_argument("workspace", type=Path)
    a.add_argument("--ghidra", type=Path, required=True)
    a.add_argument("--timeout", type=int, default=600)
    args = p.parse_args(argv)
    try:
        if args.command == 'inspect':
            result = inspect(args.input)
            if args.output:
                if args.output.exists():
                    raise FormatError("Refusing to overwrite output")
                write_json(args.output, result)
        elif args.command == 'extract-assets':
            from .disc import extract_assets
            result=extract_assets(args.input,args.output)
        elif args.command == 'prepare':
            print("Preparing input (large ZIP/ISO files may take several minutes)...", file=sys.stderr, flush=True)
            result = prepare(args.input, args.output, args.executable)
        elif args.command == 'audit':
            from .audit import audit
            result = audit(args.workspace)
        else:
            from .backend import configure, translate, analyse, export_xbe, probe, decompile_xbe
            if args.command == 'configure':
                result = configure(args.workspace, args.profile)
            elif args.command == 'translate':
                result = translate(args.workspace, args.backend, args.context, args.timeout)
            elif args.command == 'analyse':
                result = analyse(args.workspace, args.backend, args.timeout)
            elif args.command == 'probe':
                result = probe(args.workspace, args.backend, args.timeout)
            elif args.command == 'decompile-xbe':
                result = decompile_xbe(args.workspace, args.ghidra, args.timeout)
            else:
                result = export_xbe(args.workspace)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result.get('status', '').endswith('-failed') else 0
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(json.dumps(dict(status="error", error=str(exc)), ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
