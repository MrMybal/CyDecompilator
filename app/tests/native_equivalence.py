"""Behavioural equivalence of the C decompiler, checked with MSVC.

For each fixture DLL (x86/x64, /Od and /O2): decompile every export with CyDecompilator's own
C decompiler, compile the result into a second DLL with the same toolchain, then a harness
calls the original and the decompiled function on random inputs and compares the results
(and the written buffers for the functions that write memory).

    runtime/python/Scripts/python.exe app/tests/native_equivalence.py [variant ...]

Writes data/reports/native-equivalence.json. Requires Visual Studio C++ tools (vswhere).
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
FIXTURES = APP / 'tests' / 'fixtures' / 'native'
sys.path.insert(0, str(APP))

from cydec.ai.verify import msvc_vcvars  # noqa: E402
from cydec.cdec.cgen import HEADER  # noqa: E402
from cydec.cdec.decompiler import decompile  # noqa: E402
from cydec.engines.native import load_pe  # noqa: E402

# name -> (prototype for the harness, argument kinds) ; kinds: i (int), u (uint), l (long long),
# A (int array input) W (int array written) S (string)
SIGNATURES = {
    'add3': ('int (*)(int, int, int)', 'iii'), 'mix': ('unsigned (*)(unsigned)', 'u'),
    'clamp': ('int (*)(int, int, int)', 'iii'), 'sign': ('int (*)(int)', 'i'),
    'umax': ('unsigned (*)(unsigned, unsigned)', 'uu'), 'sum_to': ('int (*)(int)', 'n'),
    'gcd': ('int (*)(int, int)', 'ii'), 'collatz': ('int (*)(unsigned)', 'n'), 'popcount': ('int (*)(unsigned)', 'u'),
    'classify': ('int (*)(int)', 'c'), 'array_sum': ('int (*)(const int *, int)', 'AN'),
    'find_max': ('int (*)(const int *, int)', 'AN1'), 'fill': ('void (*)(int *, int, int)', 'WNi'),
    'strlen8': ('int (*)(const char *)', 'S'), 'mul64': ('long long (*)(long long, long long)', 'll'),
    'nested': ('int (*)(int, int)', 'nn'), 'digits': ('int (*)(unsigned)', 'u'), 'is_prime': ('int (*)(int)', 'n'),
    'bits_rev': ('int (*)(int)', 'i'), 'tri': ('int (*)(int, int, int)', 'ttt'),
    'fmix': ('double (*)(double, double)', 'dd'), 'fscale': ('float (*)(float, int)', 'fi'),
    'fpoly': ('double (*)(double)', 'd'), 'fcmp3': ('int (*)(double, double)', 'dd'),
    'fsum': ('double (*)(const double *, int)', 'FN'), 'favg': ('double (*)(int, int)', 'ii'),
    'ftrunc': ('int (*)(double)', 'd'), 'fabs2': ('double (*)(double)', 'd'),
    'fmaxd': ('double (*)(double, double)', 'dd'), 'fcall': ('double (*)(double, double)', 'dd'),
}

HARNESS = r'''
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
static unsigned long long state = 88172645463325252ULL;
static unsigned long long next(void) { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static double pickd(void) {
    unsigned long long r = next();
    if ((r & 7) == 0) return (double)((int)(r % 5) - 2);           /* small integers, ties */
    return ((double)(r >> 11) / 9007199254740992.0 - 0.5) * 2000.0;
}
static int differ(double x, double y, double tolerance) {
    if (x != x) return y == y;
    return fabs(x - y) > tolerance * (fabs(x) + 1.0);
}
static int pick(char kind) {
    unsigned long long r = next();
    switch (kind) {
    case 'n': return (int)(r % 60);
    case 'N': return (int)(r % 40);
    case 'c': return (int)(r % 12) - 2;
    case 't': return (int)(r % 3);
    case 'u': return (int)r;
    default: return (r & 3) == 0 ? (int)(r % 7) - 3 : (int)r;
    }
}
int main(int argc, char **argv)
{
    HMODULE a = LoadLibraryA(argv[1]), b = LoadLibraryA(argv[2]);
    int iterations = atoi(argv[3]);
    if (!a || !b) { printf("{\"error\": \"load\"}\n"); return 2; }
    printf("{");
@CASES@
    printf("\"done\": 1}\n");
    return 0;
}
'''

CASE = r'''
    {
        typedef %(proto)s;
        fn_t f = (fn_t)GetProcAddress(a, "%(name)s"), g = (fn_t)GetProcAddress(b, "dec_%(name)s");
        int bad = 0, crashed = 0, i;
        if (!f || !g) { printf("\"%(name)s\": \"missing\", "); }
        else {
            for (i = 0; i < iterations && bad < 3; i++) {
                __try {
%(body)s
                } __except (1) { bad++; crashed = 1; }
            }
            if (crashed) printf("\"%(name)s\": \"crash\", "); else printf("\"%(name)s\": %%d, ", bad);
        }
        fflush(stdout);
    }
'''


def case_body(name, kinds, returns):
    lines = []
    args_f, args_g = [], []
    prepare = []
    compare = []
    for index, kind in enumerate(kinds.rstrip('1')):
        var = 'p%d' % index
        if kind in 'iunct':
            prepare.append('int %s = pick(\'%s\');' % (var, kind))
            args_f.append(var)
            args_g.append(var)
        elif kind == 'l':
            prepare.append('long long %s = (long long)next() >> (next() %% 40);' % var)
            args_f.append(var)
            args_g.append(var)
        elif kind == 'N':
            prepare.append('int %s = pick(\'N\')%s;' % (var, ' + 1' if kinds.endswith('1') else ''))
            args_f.append(var)
            args_g.append(var)
        elif kind == 'A':
            prepare.append('int %s[64]; { int k; for (k = 0; k < 64; k++) %s[k] = pick(\'i\') %% 100000; }' % (var, var))
            args_f.append(var)
            args_g.append(var)
        elif kind == 'W':
            prepare.append('int %s_f[64], %s_g[64]; memset(%s_f, 0, sizeof %s_f); memset(%s_g, 0, sizeof %s_g);'
                           % ((var,) * 6))
            args_f.append(var + '_f')
            args_g.append(var + '_g')
            compare.append('memcmp(%s_f, %s_g, sizeof %s_f) != 0' % (var, var, var))
        elif kind == 'S':
            prepare.append('char %s[80]; { int k, n = pick(\'N\'); for (k = 0; k < n; k++) %s[k] = (char)(\'a\' + k %% 26); %s[n] = 0; }'
                           % (var, var, var))
            args_f.append(var)
            args_g.append(var)
        elif kind == 'd':
            prepare.append('double %s = pickd();' % var)
            args_f.append(var)
            args_g.append(var)
        elif kind == 'f':
            prepare.append('float %s = (float)pickd();' % var)
            args_f.append(var)
            args_g.append(var)
        elif kind == 'F':
            prepare.append('double %s[64]; { int k; for (k = 0; k < 64; k++) %s[k] = pickd(); }' % (var, var))
            args_f.append(var)
            args_g.append(var)
        elif kind == 'n':
            prepare.append('int %s = pick(\'n\');' % var)
            args_f.append(var)
            args_g.append(var)
    lines += ['                ' + p for p in prepare]
    if returns in ('double', 'float'):
        lines.append('                if (differ(f(%s), g(%s), %s)) bad++;'
                     % (', '.join(args_f), ', '.join(args_g), '1e-12' if returns == 'double' else '1e-6'))
    elif returns:
        lines.append('                if (f(%s) != g(%s)) bad++;' % (', '.join(args_f), ', '.join(args_g)))
    else:
        lines.append('                f(%s); g(%s);' % (', '.join(args_f), ', '.join(args_g)))
    for check in compare:
        lines.append('                if (%s) bad++;' % check)
    return '\n'.join(lines)


def compile_cmd(vcvars, arch, workdir, command):
    script = workdir / ('build_%s.cmd' % arch)
    script.write_text('@call "%s" %s >nul\r\n%s\r\n' % (vcvars.replace('vcvars64.bat', 'vcvarsall.bat'), arch, command),
                      encoding='ascii')
    result = subprocess.run(['cmd.exe', '/c', str(script)], cwd=str(workdir), capture_output=True)
    return result.returncode, (result.stdout + result.stderr).decode('oem', 'replace')


def run_variant(variant, vcvars, iterations=3000, keep=None):
    dll = FIXTURES / ('funcs_%s.dll' % variant)
    image = load_pe(dll)
    names = dict(image.exports)
    starts = set(names)
    workdir = Path(keep or tempfile.mkdtemp(prefix='cydec-eq-'))
    workdir.mkdir(parents=True, exist_ok=True)
    report = {'variant': variant, 'functions': {}}
    entries = []
    renamed = {address: 'dec_' + name for address, name in names.items()}
    for address, name in sorted(names.items(), key=lambda item: item[1]):
        try:
            decompile(image, address, 'dec_' + name, renamed, starts, 'pe')
            report['functions'][name] = {'decompiled': True}
            entries.append((address, 'dec_' + name))
        except Exception as exc:
            report['functions'][name] = {'decompiled': False, 'error': repr(exc)[:300]}
    from cydec.cdec.decompiler import module_source
    source = module_source(image, entries, renamed, starts, 'pe', export_prefix='__declspec(dllexport) ')
    (workdir / 'decompiled.c').write_text(source, encoding='utf-8')
    arch = 'x64' if '64' in variant else 'x86'
    code, output = compile_cmd(vcvars, arch, workdir, 'cl /nologo /LD /O1 /w decompiled.c /Fedecompiled.dll >build.log 2>&1')
    log = (workdir / 'build.log').read_text('oem', 'replace') if (workdir / 'build.log').exists() else output
    report['compiled'] = code == 0
    if code != 0:
        report['compileErrors'] = [line for line in log.splitlines() if 'error' in line][:40]
        # Retry function by function to find the ones that compile.
        return report, workdir
    cases = []
    for name, (proto, kinds) in SIGNATURES.items():
        if not report['functions'].get(name, {}).get('decompiled'):
            continue
        proto_type = proto.replace('(*)', '(*fn_t)')
        returns = proto.split()[0] if proto.split()[0] in ('double', 'float') else not proto.startswith('void')
        cases.append(CASE % {'proto': proto_type, 'name': name, 'body': case_body(name, kinds, returns)})
    (workdir / 'harness.c').write_text(HARNESS.replace('@CASES@', '\n'.join(cases)), encoding='utf-8')
    code, output = compile_cmd(vcvars, arch, workdir, 'cl /nologo /O1 /w harness.c /Feharness.exe >hbuild.log 2>&1')
    if code != 0:
        report['harnessErrors'] = (workdir / 'hbuild.log').read_text('oem', 'replace')[-2000:]
        return report, workdir
    result = subprocess.run([str(workdir / 'harness.exe'), str(dll), str(workdir / 'decompiled.dll'), str(iterations)],
                            capture_output=True, timeout=600)
    try:
        results = json.loads(result.stdout.decode('ascii', 'replace'))
    except ValueError:
        report['runError'] = (result.stdout + result.stderr).decode('ascii', 'replace')[-1000:] + ' exit %s' % result.returncode
        return report, workdir
    for name, bad in results.items():
        if name in report['functions']:
            report['functions'][name]['mismatches'] = bad
    report['equivalent'] = sorted(n for n, r in report['functions'].items() if r.get('mismatches') == 0)
    report['different'] = sorted(n for n, r in report['functions'].items() if r.get('mismatches') not in (0, None))
    return report, workdir


def main(variants):
    vcvars = msvc_vcvars()
    if not vcvars:
        print('Visual Studio C++ tools not found')
        return 2
    reports = []
    for variant in variants:
        report, workdir = run_variant(variant, vcvars, keep=str(ROOT / 'data' / 'reports' / 'equivalence' / variant))
        reports.append(report)
        print('%-8s compiled=%s equivalent=%d/%d different=%s %s' % (
            variant, report.get('compiled'), len(report.get('equivalent', [])), len(report['functions']),
            report.get('different', []), report.get('compileErrors', '')[:6] if not report.get('compiled') else ''))
    out = ROOT / 'data' / 'reports' / 'native-equivalence.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(reports, indent=2), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:] or ['x64_od', 'x64_o2', 'x86_od', 'x86_o2']))
