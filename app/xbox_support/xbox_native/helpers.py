"""Verify complete canonical PPC helper routines, not just short signatures."""
from __future__ import annotations

import struct


def canonical_helper(name: str) -> bytes:
    restore = name.startswith('rest')
    words = []
    if 'gprlr' in name:
        op = 58 if restore else 62
        words = [(op << 26) | (r << 21) | (1 << 16) | ((-0x98 + 8 * (r-14)) & 0xFFFF) for r in range(14, 32)]
        words += [0x8181FFF8, 0x7D8803A6] if restore else [0x9181FFF8]
    elif 'fpr' in name:
        op = 50 if restore else 54
        words = [(op << 26) | (r << 21) | (12 << 16) | ((-0x90 + 8 * (r-14)) & 0xFFFF) for r in range(14, 32)]
    elif 'vmx_14' in name:
        for r in range(14, 32):
            words += [0x39600000 | ((-0x120 + 16 * (r-14)) & 0xFFFF),
                      (0x7C0B60CE if restore else 0x7C0B61CE) | (r << 21)]
    elif 'vmx_64' in name:
        for r in range(64, 128):
            words += [0x39600000 | ((-0x400 + 16 * (r-64)) & 0xFFFF),
                      (0x100B60CB if restore else 0x100B61CB) | ((r & 31) << 21) | (4 if r >= 96 else 0)]
    else:
        raise ValueError('Unknown helper type')
    return b''.join(struct.pack('>I', w) for w in [*words, 0x4E800020])


def verify_helpers(image: bytes, base: int, candidates: dict) -> dict:
    result = {}
    for name, addresses in candidates.items():
        pattern = canonical_helper(name)
        valid = []
        for address in addresses:
            offset = address - base
            if offset >= 0 and image[offset:offset+len(pattern)] == pattern:
                valid.append(dict(address=address, size=len(pattern)))
        # A unique full routine is required before suggesting a configuration value.
        result[name] = dict(verified=valid, unique=len(valid) == 1)
    return result
