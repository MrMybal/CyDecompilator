"""Behavioural equivalence of the C decompiler on ARM64, without ARM64 hardware.

The ARM64 fixtures (built by fixtures/native/build_arm64.cmd: Windows PE and Linux ELF, -O0 and
-O2) are decompiled to one C module, compiled for x64 with MSVC and loaded with ctypes. The
original ARM64 functions run in the Unicorn CPU emulator. Both receive the same random inputs
and their results (and written buffers) are compared.

    runtime/python/Scripts/python.exe app/tests/arm64_equivalence.py [O0.dll O2.dll O0.so O2.so]

Needs the `unicorn` Python package (test-only) and Visual Studio C++ tools. Writes
data/reports/arm64-equivalence.json and keeps the work folders in data/reports/equivalence/.

Decompiled AArch64 prototypes list integer parameters first, then floating-point ones (the
registers do not say how they were interleaved), so arguments are passed in that order.
"""
import ctypes
import json
import math
import struct
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
FIXTURES = APP / 'tests' / 'fixtures' / 'native'
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / 'tests'))

from native_equivalence import SIGNATURES, compile_cmd  # noqa: E402

from cydec import detect  # noqa: E402
from cydec.ai.verify import msvc_vcvars  # noqa: E402
from cydec.cdec.decompiler import module_source  # noqa: E402
from cydec.engines.native import load  # noqa: E402

VARIANTS = ('O0.dll', 'O2.dll', 'O0.so', 'O2.so')
STACK, STACK_SIZE = 0x7f0000000000, 0x100000
DATA, DATA_SIZE = 0x7e0000000000, 0x10000
SENTINEL = 0x7d0000000000
FLOAT_KINDS = 'df'


class Random:
    """Same generator and input shapes as native_equivalence's harness."""

    def __init__(self):
        self.state = 88172645463325252

    def next(self):
        s = self.state
        s ^= (s << 13) & 0xffffffffffffffff
        s ^= s >> 7
        s ^= (s << 17) & 0xffffffffffffffff
        self.state = s
        return s

    def pick(self, kind):
        r = self.next()
        if kind == 'n':
            return r % 60
        if kind == 'N':
            return r % 40
        if kind == 'c':
            return r % 12 - 2
        if kind == 't':
            return r % 3
        if kind == 'u':
            return ctypes.c_int32(r & 0xffffffff).value
        if r & 3 == 0:
            return r % 7 - 3
        return ctypes.c_int32(r & 0xffffffff).value

    def pickd(self):
        r = self.next()
        if r & 7 == 0:
            return float(r % 5 - 2)
        return ((r >> 11) / 9007199254740992.0 - 0.5) * 2000.0


class Emulator:
    def __init__(self, image):
        from unicorn import UC_ARCH_ARM64, UC_MODE_ARM, Uc
        from unicorn import arm64_const as R
        self.R = R
        self.uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        pages = set()
        for seg in image.segments:
            start = seg.va & ~0xfff
            end = (seg.virtual_end + 0xfff) & ~0xfff
            for page in range(start, end, 0x1000):
                pages.add(page)
        for page in sorted(pages):
            self.uc.mem_map(page, 0x1000)
        for seg in image.segments:
            self.uc.mem_write(seg.va, bytes(seg.data))
        # Dynamic linking of the library's own symbols (PLT calls between its functions).
        exports = {name: address for address, name in image.exports.items()}
        for slot, name in image.import_slots.items():
            if name in exports:
                self.uc.mem_write(slot, struct.pack('<Q', exports[name]))
        self.uc.mem_map(STACK, STACK_SIZE)
        self.uc.mem_map(DATA, DATA_SIZE)
        self.uc.mem_map(SENTINEL, 0x1000)
        # Enable the FP/SIMD unit (CPACR_EL1.FPEN).
        self.uc.reg_write(R.UC_ARM64_REG_CPACR_EL1, self.uc.reg_read(R.UC_ARM64_REG_CPACR_EL1) | (3 << 20))

    def call(self, address, ints, floats, ret):
        R = self.R
        for index, value in enumerate(ints):
            self.uc.reg_write(getattr(R, 'UC_ARM64_REG_X%d' % index), value & 0xffffffffffffffff)
        for index, (kind, value) in enumerate(floats):
            if kind == 'd':
                bits = struct.unpack('<Q', struct.pack('<d', value))[0]
                self.uc.reg_write(getattr(R, 'UC_ARM64_REG_D%d' % index), bits)
            else:
                bits = struct.unpack('<I', struct.pack('<f', value))[0]
                self.uc.reg_write(getattr(R, 'UC_ARM64_REG_S%d' % index), bits)
        self.uc.reg_write(R.UC_ARM64_REG_SP, STACK + STACK_SIZE - 0x100)
        self.uc.reg_write(R.UC_ARM64_REG_LR, SENTINEL)
        self.uc.emu_start(address, SENTINEL, timeout=2000000, count=2000000)
        if ret == 'double':
            return struct.unpack('<d', struct.pack('<Q', self.uc.reg_read(R.UC_ARM64_REG_D0)))[0]
        if ret == 'float':
            return struct.unpack('<f', struct.pack('<I', self.uc.reg_read(R.UC_ARM64_REG_S0) & 0xffffffff))[0]
        x0 = self.uc.reg_read(R.UC_ARM64_REG_X0)
        if ret == 'long long':
            return ctypes.c_int64(x0).value
        if ret == 'unsigned':
            return x0 & 0xffffffff
        return ctypes.c_int32(x0 & 0xffffffff).value

    def write(self, offset, data):
        self.uc.mem_write(DATA + offset, data)
        return DATA + offset

    def read(self, offset, size):
        return bytes(self.uc.mem_read(DATA + offset, size))


CTYPES = {'int': ctypes.c_int32, 'unsigned': ctypes.c_uint32, 'long long': ctypes.c_int64,
          'double': ctypes.c_double, 'float': ctypes.c_float, 'void': None}


def return_kind(proto):
    head = proto.split('(*)')[0].strip()
    return head if head in CTYPES else 'int'


def compare(kind, a, b):
    if kind in ('double', 'float'):
        tolerance = 1e-12 if kind == 'double' else 1e-6
        if a != a:
            return b != b
        return abs(a - b) <= tolerance * (abs(a) + 1.0)
    return a == b


def run_variant(variant, vcvars, iterations=300, keep=None):
    path = FIXTURES / ('funcs_arm64_' + variant)
    image = load(path, detect.detect(path))
    names = dict(image.exports)
    renamed = {address: 'dec_' + name for address, name in names.items()}
    workdir = Path(keep)
    workdir.mkdir(parents=True, exist_ok=True)
    report = {'variant': variant, 'functions': {}}
    entries = [(address, 'dec_' + name) for address, name in sorted(names.items(), key=lambda item: item[1])]
    source = module_source(image, entries, renamed, set(names), 'pe' if variant.endswith('dll') else 'elf',
                           export_prefix='__declspec(dllexport) ')
    (workdir / 'decompiled.c').write_text(source, encoding='utf-8')
    code, _ = compile_cmd(vcvars, 'x64', workdir, 'cl /nologo /LD /O1 /w decompiled.c /Fedecompiled.dll >build.log 2>&1')
    report['compiled'] = code == 0
    if code != 0:
        log = (workdir / 'build.log').read_text('oem', 'replace')
        report['compileErrors'] = [line for line in log.splitlines() if 'error' in line][:20]
        return report
    for name in SIGNATURES:
        if name not in {n for n in names.values()}:
            continue
        # Each function runs in a child process: a decompiled loop that never ends shows up as a
        # timeout instead of blocking the whole check.
        try:
            child = subprocess.run([sys.executable, __file__, '--check', variant, str(workdir), name, str(iterations)],
                                   capture_output=True, timeout=60)
            output = child.stdout.decode('utf-8', 'replace').strip().splitlines()
            result = json.loads(output[-1]) if output else {'mismatches': 'child exit %s' % child.returncode}
        except subprocess.TimeoutExpired:
            result = {'mismatches': 'timeout'}
        except ValueError:
            result = {'mismatches': 'child output: %s' % child.stdout[-200:]}
        report['functions'][name] = result
    report['equivalent'] = sorted(n for n, r in report['functions'].items() if r['mismatches'] == 0)
    report['different'] = sorted(n for n, r in report['functions'].items() if r['mismatches'] != 0)
    return report


def check_function(variant, workdir, name, iterations):
    """Run one function: emulated original vs decompiled (in this process)."""
    path = FIXTURES / ('funcs_arm64_' + variant)
    image = load(path, detect.detect(path))
    by_name = {n: address for address, n in image.exports.items()}
    dll = ctypes.CDLL(str(Path(workdir) / 'decompiled.dll'))
    emulator = Emulator(image)
    proto, kinds = SIGNATURES[name]
    ret = return_kind(proto)
    function = getattr(dll, 'dec_' + name, None)
    if function is None:
        return {'mismatches': 'missing'}
    function.restype = CTYPES[ret]
    rng = Random()
    bad, crashed, first = 0, False, None
    for _ in range(iterations):
        ints_arm, floats_arm, args_c, types_c, buffers = [], [], [], [], []
        offset = 0
        for kind in kinds.rstrip('1'):
            if kind in 'iunct':
                value = rng.pick(kind)
                ints_arm.append(value)
                args_c.append(value)
                types_c.append(ctypes.c_int32)
            elif kind == 'l':
                value = ctypes.c_int64(rng.next()).value >> (rng.next() % 40)
                ints_arm.append(value)
                args_c.append(value)
                types_c.append(ctypes.c_int64)
            elif kind in 'Nn':
                value = rng.pick(kind) + (1 if kind == 'N' and kinds.endswith('1') else 0)
                ints_arm.append(value)
                args_c.append(value)
                types_c.append(ctypes.c_int32)
            elif kind in 'AWF':
                if kind == 'A':
                    values = [rng.pick('i') % 100000 for _ in range(64)]
                    raw = struct.pack('<64i', *[ctypes.c_int32(v).value for v in values])
                    host = (ctypes.c_int32 * 64)(*[ctypes.c_int32(v).value for v in values])
                elif kind == 'F':
                    values = [rng.pickd() for _ in range(64)]
                    raw = struct.pack('<64d', *values)
                    host = (ctypes.c_double * 64)(*values)
                else:
                    raw = bytes(256)
                    host = (ctypes.c_int32 * 64)()
                ints_arm.append(emulator.write(offset, raw))
                buffers.append((offset, host, kind))
                offset += 0x800
                args_c.append(ctypes.cast(host, ctypes.c_void_p))
                types_c.append(ctypes.c_void_p)
            elif kind == 'S':
                n = rng.pick('N')
                text = bytes((97 + k % 26) for k in range(n)) + b'\0'
                ints_arm.append(emulator.write(offset, text))
                host = ctypes.create_string_buffer(text)
                offset += 0x800
                args_c.append(ctypes.cast(host, ctypes.c_void_p))
                types_c.append(ctypes.c_void_p)
                buffers.append((None, host, 'S'))
            elif kind in FLOAT_KINDS:
                value = rng.pickd()
                if kind == 'f':
                    value = struct.unpack('<f', struct.pack('<f', value))[0]
                floats_arm.append((kind, value))
        # Decompiled prototype: integer parameters, then floating-point ones.
        for kind, value in floats_arm:
            args_c.append(value)
            types_c.append(ctypes.c_double if kind == 'd' else ctypes.c_float)
        function.argtypes = types_c
        try:
            expected = emulator.call(by_name[name], ints_arm, floats_arm, ret)
        except Exception as exc:
            return {'mismatches': 'emulator: %s' % exc}
        try:
            got = function(*args_c)
        except OSError as exc:
            crashed = True
            first = first or str(exc)
            bad += 1
            break
        ok = ret == 'void' or compare(ret, expected, got)
        for buffer_offset, host, kind in buffers:
            if kind == 'W' and emulator.read(buffer_offset, 256) != bytes(host):
                ok = False
        if not ok:
            bad += 1
            if first is None:
                first = {'args': [str(v) for v in ints_arm] + [str(v) for _, v in floats_arm],
                         'expected': str(expected), 'got': str(got)}
            if bad >= 3:
                break
    result = {'mismatches': 'crash' if crashed else bad}
    if first is not None:
        result['first'] = first
    return result


def main(variants):
    vcvars = msvc_vcvars()
    if not vcvars:
        print('Visual Studio C++ tools not found')
        return 2
    reports = []
    for variant in variants:
        report = run_variant(variant, vcvars, keep=str(ROOT / 'data' / 'reports' / 'equivalence' / ('arm64_' + variant)))
        reports.append(report)
        print('%-7s compiled=%s equivalent=%d/%d different=%s %s' % (
            variant, report.get('compiled'), len(report.get('equivalent', [])), len(SIGNATURES),
            report.get('different', []), report.get('compileErrors', '') if not report.get('compiled') else ''))
    out = ROOT / 'data' / 'reports' / 'arm64-equivalence.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(reports, indent=2), encoding='utf-8')
    return 0


if __name__ == '__main__':
    if sys.argv[1:2] == ['--check']:
        print(json.dumps(check_function(sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]))))
        sys.exit(0)
    sys.exit(main(sys.argv[1:] or list(VARIANTS)))
