"""Read-only executable metadata; unknown/encrypted code is never guessed.

Format references and provenance are recorded in docs/RESEARCH.md.
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path


class FormatError(ValueError):
    pass


def span(data: bytes, offset: int, size: int) -> bytes:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise FormatError(f"Range outside input: offset={offset:#x}, size={size:#x}")
    return data[offset:offset + size]


def u32(data: bytes, offset: int, endian: str = "<") -> int:
    return struct.unpack(endian + "I", span(data, offset, 4))[0]


def _cstring(data: bytes, offset: int, end: int) -> str:
    if not 0 <= offset < end <= len(data):
        raise FormatError("Invalid string range")
    stop = data.find(b"\0", offset, end)
    if stop < 0:
        raise FormatError("Unterminated string")
    return data[offset:stop].decode("ascii", errors="replace")


def parse_xbe(data: bytes) -> dict:
    span(data, 0, 0x178)
    if data[:4] != b"XBEH":
        raise FormatError("Expected XBEH")
    base, headers, image = (u32(data, n) for n in (0x104, 0x108, 0x10C))
    if headers < 0x178 or headers > len(data) or image < headers:
        raise FormatError("Invalid XBE header/image size")
    count, table = u32(data, 0x11C), u32(data, 0x120) - base
    if not 0 < count <= 4096 or table < 0x178 or table + count * 56 > headers:
        raise FormatError("Invalid XBE section table")
    sections = []
    for i in range(count):
        o = table + i * 56
        flags, va, virtual, raw, size, name = struct.unpack("<6I", span(data, o, 24))
        span(data, raw, size)
        if va < base or va + virtual > base + image or size > virtual:
            raise FormatError("Invalid XBE section bounds")
        sections.append(dict(name=_cstring(data, name - base, headers), address=va,
                             virtual_size=virtual, file_offset=raw, file_size=size,
                             executable=bool(flags & 4), flags=flags))
    encoded = u32(data, 0x128)
    # These are format XOR constants, not cryptographic keys. Keep ambiguity explicit.
    entries = []
    for kind, mask in (("retail", 0xA8FC57AB), ("debug", 0x94859D4B), ("chihiro", 0x40B5C16E)):
        address = encoded ^ mask
        if any(s["executable"] and s["address"] <= address < s["address"] + s["file_size"] for s in sections):
            entries.append(dict(kind=kind, address=address))
    cert = u32(data, 0x118) - base
    title, title_id = None, None
    if cert >= 0:
        span(data, cert, 0x5C)
        cert_size = u32(data, cert)
        if cert_size < 0x5C or cert + cert_size > headers:
            raise FormatError("Invalid XBE certificate")
        title_id = f"{u32(data, cert + 8):08X}"
        title = span(data, cert + 12, 80).decode("utf-16-le", errors="replace").split("\0")[0]
    imports = []
    if len(entries) == 1:
        mask = {"retail": 0x5B6D40B6, "debug": 0xEFB1F152, "chihiro": 0x2290059D}[entries[0]["kind"]]
        thunk = u32(data, 0x158) ^ mask
        if thunk:
            for s in sections:
                if s["address"] <= thunk < s["address"] + s["file_size"]:
                    off = s["file_offset"] + thunk - s["address"]
                    end = s["file_offset"] + s["file_size"]
                    for _ in range(65536):
                        if off + 4 > end:
                            raise FormatError("Unterminated XBE kernel imports")
                        value = u32(data, off)
                        off += 4
                        if not value:
                            break
                        imports.append(value & 0x7FFFFFFF)
                    else:
                        raise FormatError("Too many XBE imports")
                    break
            else:
                raise FormatError("XBE kernel thunk is outside file-backed sections")
    return dict(format="xbe", console="xbox", architecture="x86", byte_order="little",
                image_base=base, image_size=image, title=title, title_id=title_id,
                entry_candidates=entries, entry_point=entries[0]["address"] if len(entries) == 1 else None,
                kernel_import_ordinals=imports, sections=sections,
                blockers=["Xbox kernel/XAPI, graphics NV2A, audio and input require native replacements",
                          "Full Xbox x86 lifting/relinking backend is not implemented"])


def parse_xex(data: bytes) -> dict:
    span(data, 0, 24)
    if data[:4] != b"XEX2":
        raise FormatError("Expected XEX2 (XEX1 not supported)")
    payload, security, count = (u32(data, n, ">") for n in (8, 16, 20))
    if not 24 <= payload <= len(data) or count > 4096 or 24 + 8 * count > payload:
        raise FormatError("Invalid XEX optional header table")
    options = {}
    for i in range(count):
        key, value = struct.unpack(">II", span(data, 24 + i * 8, 8))
        if key in options:
            raise FormatError("Duplicate XEX optional header")
        words = key & 255
        if words > 1:
            size = u32(data, value, ">") if words == 255 else words * 4
            if size < 4 or value < 24 + count * 8 or value + size > payload:
                raise FormatError(f"Invalid XEX optional header {key:#x}")
            span(data, value, size)
        options[key] = value
    if security < 24 or security + 0x184 > payload:
        raise FormatError("Invalid XEX security header")
    security_size = u32(data, security, ">")
    if security_size < 0x184 or security + security_size > payload:
        raise FormatError("Invalid XEX security header size")
    image_size = u32(data, security + 4, ">")
    if not 0 < image_size <= 512 * 1024 * 1024:
        raise FormatError('XEX image size exceeds supported bounds')
    base = options.get(0x10201, u32(data, security + 0x110, ">"))
    entry = options.get(0x10100)
    title_id, media_id = None, None
    if 0x40006 in options:
        o = options[0x40006]
        media_id, title_id = (f"{u32(data, o + n, '>'):08X}" for n in (0, 12))
    encryption, compression = None, None
    basic_blocks = []
    if 0x3FF in options:
        o = options[0x3FF]
        size = u32(data, o, ">")
        span(data, o, 8)
        if size < 8:
            raise FormatError("Invalid XEX file format info")
        encryption, compression = struct.unpack(">HH", span(data, o + 4, 4))
        if compression == 1:
            if (size - 8) % 8:
                raise FormatError("Invalid XEX basic compression blocks")
            for n in range(o + 8, o + size, 8):
                a, b = struct.unpack(">II", span(data, n, 8))
                basic_blocks.append(dict(data_size=a, zero_size=b))
            if sum(b['data_size'] + b['zero_size'] for b in basic_blocks) > image_size:
                raise FormatError('XEX basic blocks exceed declared image size')
            if sum(b['data_size'] for b in basic_blocks) > len(data) - payload:
                raise FormatError('XEX basic blocks exceed payload size')
    libraries = []
    if 0x103FF in options:
        o = options[0x103FF]
        end = o + u32(data, o, ">")
        string_size, lib_count = u32(data, o + 4, ">"), u32(data, o + 8, ">")
        if lib_count > 4096 or o + 12 + string_size > end:
            raise FormatError("Invalid XEX import string table")
        strings = []
        p = o + 12
        while p < o + 12 + string_size:
            name = _cstring(data, p, o + 12 + string_size)
            strings.append(name)
            p += (len(name.encode('ascii', errors='replace')) + 4) & ~3
        p = o + 12 + string_size
        for _ in range(lib_count):
            if p + 40 > end:
                raise FormatError("Truncated XEX import library")
            size = u32(data, p, ">")
            index, n = struct.unpack(">HH", span(data, p + 36, 4))
            if size < 40 + 4 * n or p + size > end or index >= len(strings):
                raise FormatError("Invalid XEX import library record")
            libraries.append(dict(name=strings[index], record_count=n,
                                  record_addresses=[u32(data, p + 40 + j * 4, ">") for j in range(n)]))
            p += size
    blockers = ["Native kernel/XAM runtime, Xenos shaders/rendering, audio, input and title-specific fixes required",
                "CPU translation does not establish game compatibility"]
    if encryption != 0:
        blockers.append("Code payload is encrypted or encryption metadata is absent; local metadata reader does not decrypt it")
    if compression not in (0, 1):
        blockers.append("Code payload requires external decompression backend")
    if u32(data, 4, ">") & 0x70:
        blockers.append("Patch/delta XEX requires the matching base executable and title update handling")
    return dict(format="xex2", console="xbox360", architecture="powerpc-xenon", byte_order="big",
                module_flags=u32(data, 4, ">"),
                image_base=base, image_size=image_size, entry_point=entry,
                title_id=title_id, media_id=media_id, payload_offset=payload,
                encryption=encryption, compression=compression, basic_blocks=basic_blocks,
                import_libraries=libraries, optional_headers={f"{k:08X}": v for k, v in options.items()},
                blockers=blockers)


def inspect(path: Path) -> dict:
    if path.stat().st_size > 512 * 1024 * 1024:
        raise FormatError("Executable exceeds 512 MiB limit; prepare an ISO/ZIP first")
    data = path.read_bytes()
    if data[:4] == b"XBEH":
        result = parse_xbe(data)
    elif data[:4] == b"XEX2":
        result = parse_xex(data)
    else:
        raise FormatError("Expected Xbox XBE or Xbox 360 XEX2 executable")
    return dict(schema_version=1, source=str(path.resolve()), size=len(data),
                sha256=hashlib.sha256(data).hexdigest(), **result)
