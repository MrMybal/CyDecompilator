"""Bounded, read-only XDVDFS reader and explicit preparation into a new directory."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import struct
import zipfile

from .formats import FormatError

SECTOR = 2048
MAGIC = b"MICROSOFT*XBOX*MEDIA"
# Known partition starts, including full XGD2/XGD3 dumps and extracted XISO.
PARTITIONS = (0, 0xFB20, 0x20600, 0x2080000, 0xFD90000, 0x18300000)


class Disc:
    def __init__(self, path: Path):
        self.path = path
        self.size = path.stat().st_size
        self.file = path.open("rb")
        try:
            for base in PARTITIONS:
                if base + 33 * SECTOR > self.size:
                    continue
                descriptor = self.read(base + 32 * SECTOR, SECTOR)
                if descriptor[:20] == MAGIC and descriptor[-20:] == MAGIC:
                    self.base = base
                    self.root_sector, self.root_size = struct.unpack_from("<II", descriptor, 20)
                    break
            else:
                raise FormatError("No XDVDFS descriptor found at known Xbox/XGD2/XGD3 partition offsets")
        except BaseException:
            self.file.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.file.close()

    def read(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0 or offset + size > self.size:
            raise FormatError("Disc extent outside image")
        self.file.seek(offset)
        data = self.file.read(size)
        if len(data) != size:
            raise FormatError("Short disc read")
        return data

    def entries(self, max_entries: int = 100000) -> list[dict]:
        result, names, directories = [], set(), set()
        pending = [(self.root_sector, self.root_size, "", 0)]
        while pending:
            sector, size, parent, depth = pending.pop()
            if depth > 64 or size < 14 or size > 32 * 1024 * 1024:
                raise FormatError("Invalid XDVDFS directory size/depth")
            if (sector, size) in directories:
                raise FormatError("XDVDFS directory cycle or alias")
            directories.add((sector, size))
            data = self.read(self.base + sector * SECTOR, size)
            nodes, visited = [0], set()
            while nodes:
                offset = nodes.pop()
                if offset in visited:
                    raise FormatError("XDVDFS directory node cycle")
                visited.add(offset)
                if offset + 14 > size:
                    raise FormatError("XDVDFS directory node outside table")
                left, right, start, length, attributes, n = struct.unpack_from("<HHIIBB", data, offset)
                if not n or offset + 14 + n > size:
                    raise FormatError("Invalid XDVDFS filename length")
                name = data[offset + 14:offset + 14 + n].decode("ascii", errors="strict")
                if name in (".", "..") or any(c in name for c in '/\\:\0') or name.rstrip(" .") != name:
                    raise FormatError("Unsafe XDVDFS filename")
                path = f"{parent}/{name}" if parent else name
                if path.casefold() in names:
                    raise FormatError("Duplicate XDVDFS path")
                names.add(path.casefold())
                absolute = self.base + start * SECTOR
                if absolute > self.size or length > self.size - absolute:
                    raise FormatError("XDVDFS file/directory outside image")
                is_dir = bool(attributes & 0x10)
                result.append(dict(path=path, offset=absolute, size=length, directory=is_dir))
                if len(result) > max_entries:
                    raise FormatError("XDVDFS entry limit exceeded")
                if is_dir and length:
                    pending.append((start, length, path, depth + 1))
                if right:
                    nodes.append(right * 4)
                if left:
                    nodes.append(left * 4)
        return sorted(result, key=lambda e: e["path"].casefold())

    def copy(self, entry: dict, target: Path):
        if entry["directory"]:
            raise FormatError("Cannot copy directory as a file")
        self.file.seek(entry["offset"])
        remaining = entry["size"]
        digest = hashlib.sha256()
        with target.open("xb") as out:
            while remaining:
                block = self.file.read(min(4 * 1024 * 1024, remaining))
                if not block:
                    raise FormatError("Short read during disc extraction")
                out.write(block)
                digest.update(block)
                remaining -= len(block)
        return digest.hexdigest()


def extract_assets(image: Path, output: Path) -> dict:
    """Extract a validated disc into a new asset root, preserving every input byte."""
    image,output=image.resolve(strict=True),output.resolve()
    if image==output:raise FormatError('Asset output must be separate from the input')
    with Disc(image) as disc:
        entries=disc.entries()
        total=sum(e['size'] for e in entries if not e['directory'])
        output.mkdir(parents=True,exist_ok=False)
        if shutil.disk_usage(output).free<total+256*1024**2:raise FormatError('Insufficient space for game assets')
        files=[]
        for e in entries:
            relative=PurePosixPath(e['path'])
            target=output.joinpath(*relative.parts).resolve()
            if output not in target.parents:raise FormatError('Disc path leaves asset root')
            if e['directory']:
                target.mkdir(parents=True,exist_ok=True)
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                digest=disc.copy(e,target)
                files.append(dict(path=e['path'],size=e['size'],sha256=digest))
        receipt=dict(schema_version=1,status='assets-extracted',source=str(image),output=str(output),
                     total_bytes=total,file_count=len(files),files=files,native_game_ready=False)
        receipt_path=output.parent/(output.name+'-receipt.json')
        with receipt_path.open('x',encoding='utf-8') as f:json.dump(receipt,f,indent=2)
        return {k:v for k,v in receipt.items() if k!='files'}|dict(receipt=str(receipt_path))


def write_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(source: Path, output: Path, executable: str | None = None) -> dict:
    """Create a fresh workspace; never write beside the input or overwrite work.

    Only the selected executable is copied from disc/folder. Assets stay referenced.
    A ZIP containing an ISO is streamed to a fixed local name, never extractall().
    """
    source, output = source.resolve(strict=True), output.resolve()
    if output == source or (source.is_dir() and source in output.parents):
        raise FormatError("Output must be outside the source folder")
    output.mkdir(parents=True, exist_ok=False)
    private = output / "private"
    private.mkdir()
    (output / ".gitignore").write_text("private/\ngenerated/\nbuild/\nlogs/\n", encoding="utf-8")
    receipt = dict(schema_version=1, source=str(source), status="preparing")
    write_json(output / "prepare.json", receipt)
    try:
        image = source
        if source.is_file() and zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as archive:
                isos = [i for i in archive.infolist() if not i.is_dir() and i.filename.lower().endswith('.iso')]
                if len(isos) != 1:
                    raise FormatError("ZIP must contain exactly one ISO; extract other archive layouts first")
                item = isos[0]
                if item.flag_bits & 1 or item.file_size > 32 * 1024**3:
                    raise FormatError("Encrypted ZIP or ISO above 32 GiB limit")
                if shutil.disk_usage(output).free < item.file_size + 512 * 1024**2:
                    raise FormatError("Insufficient free space for ISO staging")
                image = private / "disc.iso"
                with archive.open(item) as inp, image.open("xb") as out:
                    shutil.copyfileobj(inp, out, 4 * 1024 * 1024)
                if image.stat().st_size != item.file_size:
                    raise FormatError("ISO extraction size mismatch")
                receipt["zip_member"] = item.filename
        if source.is_dir():
            candidates = [p for p in source.rglob('*') if p.is_file() and p.suffix.lower() in ('.xbe', '.xex')]
            if executable:
                candidates = [p for p in candidates if p.relative_to(source).as_posix().casefold() == executable.casefold()]
            else:
                defaults = [p for p in candidates if p.name.casefold() in ('default.xbe', 'default.xex')]
                candidates = defaults or candidates
            if len(candidates) != 1:
                raise FormatError("Choose a unique executable using --executable relative/path")
            chosen = candidates[0].resolve(strict=True)
            if source not in chosen.parents:
                raise FormatError("Executable symlink leaves source directory")
            target = private / ("default" + chosen.suffix.lower())
            with chosen.open("rb") as inp, target.open("xb") as out:
                shutil.copyfileobj(inp, out)
            receipt["asset_root"] = str(source)
            receipt["selected_executable"] = str(chosen)
        else:
            with image.open('rb') as stream:
                magic = stream.read(4)
            if magic in (b'XBEH', b'XEX2'):
                target = private / ("default.xbe" if magic == b'XBEH' else "default.xex")
                with image.open("rb") as inp, target.open("xb") as out:
                    shutil.copyfileobj(inp, out)
                receipt["asset_root"] = str(source.parent)
            else:
                with Disc(image) as disc:
                    entries = disc.entries()
                    write_json(output / "disc-index.json", dict(partition_offset=disc.base, entries=entries))
                    candidates = [e for e in entries if not e['directory'] and
                                  (e['path'].casefold() == executable.casefold() if executable else
                                   e['path'].casefold() in ('default.xbe', 'default.xex'))]
                    if len(candidates) != 1:
                        raise FormatError("Choose a unique disc executable using --executable")
                    entry = candidates[0]
                    target = private / ("default" + PurePosixPath(entry['path']).suffix.lower())
                    disc.copy(entry, target)
                    receipt.update(disc_image=str(image), partition_offset=disc.base,
                                   selected_executable=entry['path'], disc_entry_count=len(entries))
        from .formats import inspect
        report = inspect(target)
        write_json(output / "analysis.json", report)
        receipt.update(status="prepared", executable=target.relative_to(output).as_posix(),
                       sha256=sha256(target), console=report['console'])
    except BaseException as exc:
        receipt.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        write_json(output / "prepare.json", receipt)
        raise
    write_json(output / "prepare.json", receipt)
    return receipt
