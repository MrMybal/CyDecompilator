/* Pure test functions for the CyDecompilator C decompiler: compiled with MSVC (x86/x64, /Od and /O2),
   decompiled, recompiled, and compared on random inputs. */
#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT __attribute__((visibility("default")))
#endif

EXPORT int add3(int a, int b, int c) { return a + b * c - 7; }
EXPORT unsigned int mix(unsigned int x) { x ^= x >> 13; x *= 0x5bd1e995u; x ^= x >> 15; return x; }
EXPORT int clamp(int v, int lo, int hi) { if (v < lo) return lo; if (v > hi) return hi; return v; }
EXPORT int sign(int v) { return (v > 0) - (v < 0); }
EXPORT unsigned int umax(unsigned int a, unsigned int b) { return a > b ? a : b; }
EXPORT int sum_to(int n) { int s = 0; for (int i = 1; i <= n; i++) s += i; return s; }
EXPORT int gcd(int a, int b) { while (b != 0) { int t = a % b; a = b; b = t; } return a < 0 ? -a : a; }
EXPORT int collatz(unsigned int n) { int steps = 0; while (n > 1 && steps < 1000) { n = (n & 1) ? 3 * n + 1 : n / 2; steps++; } return steps; }
EXPORT int popcount(unsigned int x) { int c = 0; while (x) { x &= x - 1; c++; } return c; }
EXPORT int classify(int code)
{
    switch (code) {
    case 0: return 100;
    case 1: return 250;
    case 2: return -3;
    case 3: return 77;
    case 4: return code * 9;
    case 5: return 1234;
    case 7: return 42;
    default: return -1;
    }
}
EXPORT int array_sum(const int *data, int count) { int s = 0; for (int i = 0; i < count; i++) s += data[i]; return s; }
EXPORT int find_max(const int *data, int count) { int best = data[0]; for (int i = 1; i < count; i++) if (data[i] > best) best = data[i]; return best; }
EXPORT void fill(int *data, int count, int value) { for (int i = 0; i < count; i++) data[i] = value + i; }
EXPORT int strlen8(const char *s) { int n = 0; while (s[n]) n++; return n; }
EXPORT long long mul64(long long a, long long b) { return a * b + (a >> 3); }
EXPORT int nested(int a, int b) { int r = 0; for (int i = 0; i < a; i++) { for (int j = 0; j < b; j++) { if ((i + j) % 3 == 0) r += i; else r -= j; } } return r; }
EXPORT int digits(unsigned int v) { int d = 1; while (v >= 10) { v /= 10; d++; } return d; }
EXPORT int is_prime(int n) { if (n < 2) return 0; for (int i = 2; i * i <= n; i++) if (n % i == 0) return 0; return 1; }
EXPORT int bits_rev(int x) { int r = 0; for (int i = 0; i < 8; i++) { r = (r << 1) | (x & 1); x >>= 1; } return r; }
EXPORT int tri(int a, int b, int c) { if (a == b && b == c) return 3; if (a == b || b == c || a == c) return 2; return 1; }
/* Floating point: SSE scalar code on x64, x87 returns (and x87 or SSE2 math) on x86. */
EXPORT double fmix(double a, double b) { return a * 1.5 + b / 3.0 - 2.25; }
EXPORT float fscale(float x, int n) { return x * (float)n + 0.5f; }
EXPORT double fpoly(double x) { return ((x * 0.5 + 1.0) * x - 3.0) * x; }
EXPORT int fcmp3(double a, double b) { return a < b ? -1 : (a > b ? 1 : 0); }
EXPORT double fsum(const double *v, int n) { double s = 0.0; for (int i = 0; i < n; i++) s += v[i]; return s; }
EXPORT double favg(int a, int b) { return (a + b) / 2.0; }
EXPORT int ftrunc(double x) { return (int)x; }
EXPORT double fabs2(double x) { return x < 0 ? -x : x; }
EXPORT double fmaxd(double a, double b) { return a > b ? a : b; }
EXPORT double fcall(double a, double b) { return fmix(a, b) * 2.0 + fpoly(b); }
