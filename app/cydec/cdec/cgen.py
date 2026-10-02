"""C generation: variable naming and narrowing, light type inference, expression printing.

Integer semantics are kept exact: values are bit patterns of a given size, signedness only
matters for >>, /, %, ordered comparisons and widening, and the printer adds a cast exactly
there when the operand's declared type does not already have the needed signedness. Narrow
(8/16-bit) arithmetic is re-truncated before it is compared or divided, as C promotes it.
"""
import re

from .ir import (Addr, Assign, Bin, Branch, Call, Cast, Cmp, Comment, Cond, Const, ExprStmt, FConst, Flags,
                 Intrinsic, Load, Logic, Ret, Store, Switch, Sym, Tern, Un, Var, mask, signed)
from .ir import FLOAT_FUNCTIONS
from .structure import Structurer

INT_NAMES = {(1, True): 'char', (1, False): 'byte', (2, True): 'short', (2, False): 'ushort', (4, True): 'int',
             (4, False): 'uint', (8, True): 'longlong', (8, False): 'ulonglong', (16, False): 'uint128'}
PREFIX = {(1, True): 'c', (1, False): 'b', (2, True): 's', (2, False): 'us', (4, True): 'i', (4, False): 'u',
          (8, True): 'l', (8, False): 'ul', (16, False): 'auVar'}
PRECEDENCE = {'*': 3, '/': 3, '%': 3, '+': 4, '-': 4, '<<': 5, '>>': 5, '<': 6, '<=': 6, '>': 6, '>=': 6,
              '==': 7, '!=': 7, '&': 8, '^': 9, '|': 10, '&&': 11, '||': 12}

HEADER = '''/* Types and helpers used by CyDecompilator's C output. */
#include <immintrin.h>
#include <string.h>
#include <math.h>
#ifdef _MSC_VER
#include <intrin.h>
#endif
#ifndef __cplusplus
#define true 1
#define false 0
#endif
typedef unsigned char byte; typedef unsigned short ushort; typedef unsigned int uint;
typedef long long longlong; typedef unsigned long long ulonglong;
typedef struct { ulonglong lo, hi; } uint128;
typedef ulonglong code();
#ifdef _MSC_VER
#define CY_INLINE static __inline
#else
#define CY_INLINE static inline
#endif
/* Bit operations without a C operator (AArch64 clz/rbit/rev, saturating conversions...). */
CY_INLINE uint cy_clz32(uint x) { uint n = 0; if (!x) return 32; while (!(x & 0x80000000u)) { x <<= 1; n++; } return n; }
CY_INLINE ulonglong cy_clz64(ulonglong x) { ulonglong n = 0; if (!x) return 64; while (!(x >> 63)) { x <<= 1; n++; } return n; }
CY_INLINE uint cy_ctz32(uint x) { uint n = 0; if (!x) return 32; while (!(x & 1)) { x >>= 1; n++; } return n; }
CY_INLINE ulonglong cy_ctz64(ulonglong x) { ulonglong n = 0; if (!x) return 64; while (!(x & 1)) { x >>= 1; n++; } return n; }
CY_INLINE uint cy_cls32(uint x) { return cy_clz32(x ^ (uint)((int)x >> 31) << 1 | 1); }
CY_INLINE ulonglong cy_cls64(ulonglong x) { return cy_clz64(x ^ (ulonglong)((longlong)x >> 63) << 1 | 1); }
CY_INLINE uint cy_popcount32(uint x) { uint n = 0; while (x) { x &= x - 1; n++; } return n; }
CY_INLINE ulonglong cy_popcount64(ulonglong x) { ulonglong n = 0; while (x) { x &= x - 1; n++; } return n; }
CY_INLINE uint cy_rbit32(uint x) { uint r = 0; int i; for (i = 0; i < 32; i++) { r = r << 1 | (x & 1); x >>= 1; } return r; }
CY_INLINE ulonglong cy_rbit64(ulonglong x) { ulonglong r = 0; int i; for (i = 0; i < 64; i++) { r = r << 1 | (x & 1); x >>= 1; } return r; }
CY_INLINE uint cy_bswap32(uint x) { return x >> 24 | (x >> 8 & 0xff00) | (x << 8 & 0xff0000) | x << 24; }
CY_INLINE ulonglong cy_bswap64(ulonglong x) { return (ulonglong)cy_bswap32((uint)x) << 32 | cy_bswap32((uint)(x >> 32)); }
CY_INLINE uint cy_rev16_32(uint x) { return (x >> 8 & 0x00ff00ffu) | (x << 8 & 0xff00ff00u); }
CY_INLINE ulonglong cy_rev16_64(ulonglong x) { return (x >> 8 & 0x00ff00ff00ff00ffull) | (x << 8 & 0xff00ff00ff00ff00ull); }
CY_INLINE ulonglong cy_rev32_64(ulonglong x) { return (ulonglong)cy_bswap32((uint)x) | (ulonglong)cy_bswap32((uint)(x >> 32)) << 32; }
CY_INLINE uint cy_abs32(uint x) { return (int)x < 0 ? 0u - x : x; }
CY_INLINE ulonglong cy_abs64(ulonglong x) { return (longlong)x < 0 ? 0ull - x : x; }
CY_INLINE uint cy_ror32(uint x, uint n) { n &= 31; return n ? x >> n | x << (32 - n) : x; }
CY_INLINE ulonglong cy_ror64(ulonglong x, ulonglong n) { n &= 63; return n ? x >> n | x << (64 - n) : x; }
CY_INLINE uint cy_bits32(__m128 v) { return (uint)_mm_cvtsi128_si32(_mm_castps_si128(v)); }
CY_INLINE ulonglong cy_bits64(__m128d v) { ulonglong r; double d = _mm_cvtsd_f64(v); memcpy(&r, &d, 8); return r; }
CY_INLINE float cy_float32(uint x) { float f; memcpy(&f, &x, 4); return f; }
CY_INLINE double cy_float64(ulonglong x) { double d; memcpy(&d, &x, 8); return d; }
CY_INLINE double cy_u2f32(uint x) { return (double)x; }
CY_INLINE double cy_u2f64(ulonglong x) { return (double)(longlong)(x >> 1 | (x & 1)) * 2.0 * ((longlong)x < 0) + (double)(longlong)x * ((longlong)x >= 0); }
CY_INLINE uint cy_f2s32(double d) { return d != d ? 0 : d >= 2147483647.0 ? 0x7fffffffu : d <= -2147483648.0 ? 0x80000000u : (uint)(int)d; }
CY_INLINE ulonglong cy_f2s64(double d) { return d != d ? 0 : d >= 9223372036854775807.0 ? 0x7fffffffffffffffull : d <= -9223372036854775808.0 ? 0x8000000000000000ull : (ulonglong)(longlong)d; }
CY_INLINE uint cy_f2u32(double d) { return d != d || d <= 0 ? 0 : d >= 4294967295.0 ? 0xffffffffu : (uint)(ulonglong)d; }
CY_INLINE ulonglong cy_f2u64(double d) { return d != d || d <= 0 ? 0 : d >= 18446744073709551615.0 ? 0xffffffffffffffffull : d >= 9223372036854775808.0 ? (ulonglong)(longlong)(d - 9223372036854775808.0) + 0x8000000000000000ull : (ulonglong)(longlong)d; }
/* NEON reductions on SSE vectors. */
CY_INLINE uint cy_addv_epi32(__m128i v) { v = _mm_add_epi32(v, _mm_shuffle_epi32(v, 0x4e)); v = _mm_add_epi32(v, _mm_shuffle_epi32(v, 0xb1)); return (uint)_mm_cvtsi128_si32(v); }
CY_INLINE ulonglong cy_addv_epi64(__m128i v) { return (ulonglong)_mm_cvtsi128_si64(_mm_add_epi64(v, _mm_unpackhi_epi64(v, v))); }
CY_INLINE uint cy_maxv_epi32(__m128i v) { v = _mm_max_epi32(v, _mm_shuffle_epi32(v, 0x4e)); v = _mm_max_epi32(v, _mm_shuffle_epi32(v, 0xb1)); return (uint)_mm_cvtsi128_si32(v); }
CY_INLINE uint cy_minv_epi32(__m128i v) { v = _mm_min_epi32(v, _mm_shuffle_epi32(v, 0x4e)); v = _mm_min_epi32(v, _mm_shuffle_epi32(v, 0xb1)); return (uint)_mm_cvtsi128_si32(v); }
CY_INLINE uint cy_maxv_epu32(__m128i v) { v = _mm_max_epu32(v, _mm_shuffle_epi32(v, 0x4e)); v = _mm_max_epu32(v, _mm_shuffle_epi32(v, 0xb1)); return (uint)_mm_cvtsi128_si32(v); }
CY_INLINE uint cy_minv_epu32(__m128i v) { v = _mm_min_epu32(v, _mm_shuffle_epi32(v, 0x4e)); v = _mm_min_epu32(v, _mm_shuffle_epi32(v, 0xb1)); return (uint)_mm_cvtsi128_si32(v); }
CY_INLINE __m128i cy_cnt_epi8(__m128i v) { byte b[16]; int i; _mm_storeu_si128((__m128i *)b, v); for (i = 0; i < 16; i++) b[i] = (byte)cy_popcount32(b[i]); return _mm_loadu_si128((__m128i *)b); }
CY_INLINE uint cy_addv_epu8_8(__m128i v) { byte b[16]; uint s = 0; int i; _mm_storeu_si128((__m128i *)b, v); for (i = 0; i < 8; i++) s += b[i]; return s; }
CY_INLINE uint cy_addv_epu8_16(__m128i v) { byte b[16]; uint s = 0; int i; _mm_storeu_si128((__m128i *)b, v); for (i = 0; i < 16; i++) s += b[i]; return s; }
CY_INLINE __m128i cy_addp_8_8(__m128i a, __m128i b) { byte s[32], r[16 / sizeof(byte)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 8), b); for (i = 0; i < 8; i++) { byte x = s[2 * i], y = s[2 * i + 1]; r[i] = (byte)(x + y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_addp_8_16(__m128i a, __m128i b) { byte s[32], r[16 / sizeof(byte)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 16), b); for (i = 0; i < 16; i++) { byte x = s[2 * i], y = s[2 * i + 1]; r[i] = (byte)(x + y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_addp_16_8(__m128i a, __m128i b) { ushort s[16], r[16 / sizeof(ushort)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 4), b); for (i = 0; i < 4; i++) { ushort x = s[2 * i], y = s[2 * i + 1]; r[i] = (ushort)(x + y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_addp_16_16(__m128i a, __m128i b) { ushort s[16], r[16 / sizeof(ushort)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 8), b); for (i = 0; i < 8; i++) { ushort x = s[2 * i], y = s[2 * i + 1]; r[i] = (ushort)(x + y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_addp_32_8(__m128i a, __m128i b) { uint s[8], r[16 / sizeof(uint)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 2), b); for (i = 0; i < 2; i++) { uint x = s[2 * i], y = s[2 * i + 1]; r[i] = (uint)(x + y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_addp_32_16(__m128i a, __m128i b) { uint s[8], r[16 / sizeof(uint)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 4), b); for (i = 0; i < 4; i++) { uint x = s[2 * i], y = s[2 * i + 1]; r[i] = (uint)(x + y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_addp_64_16(__m128i a, __m128i b) { ulonglong s[4], r[16 / sizeof(ulonglong)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 2), b); for (i = 0; i < 2; i++) { ulonglong x = s[2 * i], y = s[2 * i + 1]; r[i] = (ulonglong)(x + y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_umaxp_8_8(__m128i a, __m128i b) { byte s[32], r[16 / sizeof(byte)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 8), b); for (i = 0; i < 8; i++) { byte x = s[2 * i], y = s[2 * i + 1]; r[i] = (byte)(x > y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_umaxp_8_16(__m128i a, __m128i b) { byte s[32], r[16 / sizeof(byte)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 16), b); for (i = 0; i < 16; i++) { byte x = s[2 * i], y = s[2 * i + 1]; r[i] = (byte)(x > y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_umaxp_16_8(__m128i a, __m128i b) { ushort s[16], r[16 / sizeof(ushort)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 4), b); for (i = 0; i < 4; i++) { ushort x = s[2 * i], y = s[2 * i + 1]; r[i] = (ushort)(x > y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_umaxp_16_16(__m128i a, __m128i b) { ushort s[16], r[16 / sizeof(ushort)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 8), b); for (i = 0; i < 8; i++) { ushort x = s[2 * i], y = s[2 * i + 1]; r[i] = (ushort)(x > y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_umaxp_32_8(__m128i a, __m128i b) { uint s[8], r[16 / sizeof(uint)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 2), b); for (i = 0; i < 2; i++) { uint x = s[2 * i], y = s[2 * i + 1]; r[i] = (uint)(x > y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_umaxp_32_16(__m128i a, __m128i b) { uint s[8], r[16 / sizeof(uint)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 4), b); for (i = 0; i < 4; i++) { uint x = s[2 * i], y = s[2 * i + 1]; r[i] = (uint)(x > y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_umaxp_64_16(__m128i a, __m128i b) { ulonglong s[4], r[16 / sizeof(ulonglong)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 2), b); for (i = 0; i < 2; i++) { ulonglong x = s[2 * i], y = s[2 * i + 1]; r[i] = (ulonglong)(x > y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_uminp_8_8(__m128i a, __m128i b) { byte s[32], r[16 / sizeof(byte)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 8), b); for (i = 0; i < 8; i++) { byte x = s[2 * i], y = s[2 * i + 1]; r[i] = (byte)(x < y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_uminp_8_16(__m128i a, __m128i b) { byte s[32], r[16 / sizeof(byte)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 16), b); for (i = 0; i < 16; i++) { byte x = s[2 * i], y = s[2 * i + 1]; r[i] = (byte)(x < y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_uminp_16_8(__m128i a, __m128i b) { ushort s[16], r[16 / sizeof(ushort)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 4), b); for (i = 0; i < 4; i++) { ushort x = s[2 * i], y = s[2 * i + 1]; r[i] = (ushort)(x < y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_uminp_16_16(__m128i a, __m128i b) { ushort s[16], r[16 / sizeof(ushort)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 8), b); for (i = 0; i < 8; i++) { ushort x = s[2 * i], y = s[2 * i + 1]; r[i] = (ushort)(x < y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_uminp_32_8(__m128i a, __m128i b) { uint s[8], r[16 / sizeof(uint)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 2), b); for (i = 0; i < 2; i++) { uint x = s[2 * i], y = s[2 * i + 1]; r[i] = (uint)(x < y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_uminp_32_16(__m128i a, __m128i b) { uint s[8], r[16 / sizeof(uint)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 4), b); for (i = 0; i < 4; i++) { uint x = s[2 * i], y = s[2 * i + 1]; r[i] = (uint)(x < y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_uminp_64_16(__m128i a, __m128i b) { ulonglong s[4], r[16 / sizeof(ulonglong)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 2), b); for (i = 0; i < 2; i++) { ulonglong x = s[2 * i], y = s[2 * i + 1]; r[i] = (ulonglong)(x < y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_smaxp_8_8(__m128i a, __m128i b) { byte s[32], r[16 / sizeof(byte)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 8), b); for (i = 0; i < 8; i++) { byte x = s[2 * i], y = s[2 * i + 1]; r[i] = (byte)((signed char)x > (signed char)y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_smaxp_8_16(__m128i a, __m128i b) { byte s[32], r[16 / sizeof(byte)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 16), b); for (i = 0; i < 16; i++) { byte x = s[2 * i], y = s[2 * i + 1]; r[i] = (byte)((signed char)x > (signed char)y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_smaxp_16_8(__m128i a, __m128i b) { ushort s[16], r[16 / sizeof(ushort)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 4), b); for (i = 0; i < 4; i++) { ushort x = s[2 * i], y = s[2 * i + 1]; r[i] = (ushort)((short)x > (short)y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_smaxp_16_16(__m128i a, __m128i b) { ushort s[16], r[16 / sizeof(ushort)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 8), b); for (i = 0; i < 8; i++) { ushort x = s[2 * i], y = s[2 * i + 1]; r[i] = (ushort)((short)x > (short)y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_smaxp_32_8(__m128i a, __m128i b) { uint s[8], r[16 / sizeof(uint)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 2), b); for (i = 0; i < 2; i++) { uint x = s[2 * i], y = s[2 * i + 1]; r[i] = (uint)((int)x > (int)y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_smaxp_32_16(__m128i a, __m128i b) { uint s[8], r[16 / sizeof(uint)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 4), b); for (i = 0; i < 4; i++) { uint x = s[2 * i], y = s[2 * i + 1]; r[i] = (uint)((int)x > (int)y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_smaxp_64_16(__m128i a, __m128i b) { ulonglong s[4], r[16 / sizeof(ulonglong)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 2), b); for (i = 0; i < 2; i++) { ulonglong x = s[2 * i], y = s[2 * i + 1]; r[i] = (ulonglong)((longlong)x > (longlong)y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_sminp_8_8(__m128i a, __m128i b) { byte s[32], r[16 / sizeof(byte)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 8), b); for (i = 0; i < 8; i++) { byte x = s[2 * i], y = s[2 * i + 1]; r[i] = (byte)((signed char)x < (signed char)y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_sminp_8_16(__m128i a, __m128i b) { byte s[32], r[16 / sizeof(byte)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 16), b); for (i = 0; i < 16; i++) { byte x = s[2 * i], y = s[2 * i + 1]; r[i] = (byte)((signed char)x < (signed char)y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_sminp_16_8(__m128i a, __m128i b) { ushort s[16], r[16 / sizeof(ushort)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 4), b); for (i = 0; i < 4; i++) { ushort x = s[2 * i], y = s[2 * i + 1]; r[i] = (ushort)((short)x < (short)y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_sminp_16_16(__m128i a, __m128i b) { ushort s[16], r[16 / sizeof(ushort)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 8), b); for (i = 0; i < 8; i++) { ushort x = s[2 * i], y = s[2 * i + 1]; r[i] = (ushort)((short)x < (short)y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_sminp_32_8(__m128i a, __m128i b) { uint s[8], r[16 / sizeof(uint)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 2), b); for (i = 0; i < 2; i++) { uint x = s[2 * i], y = s[2 * i + 1]; r[i] = (uint)((int)x < (int)y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_sminp_32_16(__m128i a, __m128i b) { uint s[8], r[16 / sizeof(uint)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 4), b); for (i = 0; i < 4; i++) { uint x = s[2 * i], y = s[2 * i + 1]; r[i] = (uint)((int)x < (int)y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_sminp_64_16(__m128i a, __m128i b) { ulonglong s[4], r[16 / sizeof(ulonglong)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, a); _mm_storeu_si128((__m128i *)(s + 2), b); for (i = 0; i < 2; i++) { ulonglong x = s[2 * i], y = s[2 * i + 1]; r[i] = (ulonglong)((longlong)x < (longlong)y ? x : y); } return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_shrn_16(__m128i v, int n) { ushort s[16 / sizeof(ushort)]; byte r[16 / sizeof(byte)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, v); for (i = 0; i < (int)(16 / sizeof(ushort)); i++) r[i] = (byte)((s[i]) >> n); return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_rshrn_16(__m128i v, int n) { ushort s[16 / sizeof(ushort)]; byte r[16 / sizeof(byte)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, v); for (i = 0; i < (int)(16 / sizeof(ushort)); i++) r[i] = (byte)((s[i] + (n ? (ushort)1 << (n - 1) : 0)) >> n); return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_shrn_32(__m128i v, int n) { uint s[16 / sizeof(uint)]; ushort r[16 / sizeof(ushort)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, v); for (i = 0; i < (int)(16 / sizeof(uint)); i++) r[i] = (ushort)((s[i]) >> n); return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_rshrn_32(__m128i v, int n) { uint s[16 / sizeof(uint)]; ushort r[16 / sizeof(ushort)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, v); for (i = 0; i < (int)(16 / sizeof(uint)); i++) r[i] = (ushort)((s[i] + (n ? (uint)1 << (n - 1) : 0)) >> n); return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_shrn_64(__m128i v, int n) { ulonglong s[16 / sizeof(ulonglong)]; uint r[16 / sizeof(uint)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, v); for (i = 0; i < (int)(16 / sizeof(ulonglong)); i++) r[i] = (uint)((s[i]) >> n); return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_rshrn_64(__m128i v, int n) { ulonglong s[16 / sizeof(ulonglong)]; uint r[16 / sizeof(uint)]; int i; memset(r, 0, sizeof r); _mm_storeu_si128((__m128i *)s, v); for (i = 0; i < (int)(16 / sizeof(ulonglong)); i++) r[i] = (uint)((s[i] + (n ? (ulonglong)1 << (n - 1) : 0)) >> n); return _mm_loadu_si128((__m128i *)r); }
CY_INLINE uint cy_addv_8_8(__m128i v) { byte s[16 / sizeof(byte)]; byte r; int i; _mm_storeu_si128((__m128i *)s, v); r = s[0]; for (i = 1; i < 8; i++) { byte x = s[i]; r = (byte)(r + x); } return (uint)r; }
CY_INLINE uint cy_addv_8_16(__m128i v) { byte s[16 / sizeof(byte)]; byte r; int i; _mm_storeu_si128((__m128i *)s, v); r = s[0]; for (i = 1; i < 16; i++) { byte x = s[i]; r = (byte)(r + x); } return (uint)r; }
CY_INLINE uint cy_addv_16_4(__m128i v) { ushort s[16 / sizeof(ushort)]; ushort r; int i; _mm_storeu_si128((__m128i *)s, v); r = s[0]; for (i = 1; i < 4; i++) { ushort x = s[i]; r = (ushort)(r + x); } return (uint)r; }
CY_INLINE uint cy_addv_16_8(__m128i v) { ushort s[16 / sizeof(ushort)]; ushort r; int i; _mm_storeu_si128((__m128i *)s, v); r = s[0]; for (i = 1; i < 8; i++) { ushort x = s[i]; r = (ushort)(r + x); } return (uint)r; }
CY_INLINE uint cy_umaxv_8_8(__m128i v) { byte s[16 / sizeof(byte)]; byte r; int i; _mm_storeu_si128((__m128i *)s, v); r = s[0]; for (i = 1; i < 8; i++) { byte x = s[i]; r = (byte)(x > r ? x : r); } return (uint)r; }
CY_INLINE uint cy_umaxv_8_16(__m128i v) { byte s[16 / sizeof(byte)]; byte r; int i; _mm_storeu_si128((__m128i *)s, v); r = s[0]; for (i = 1; i < 16; i++) { byte x = s[i]; r = (byte)(x > r ? x : r); } return (uint)r; }
CY_INLINE uint cy_umaxv_16_4(__m128i v) { ushort s[16 / sizeof(ushort)]; ushort r; int i; _mm_storeu_si128((__m128i *)s, v); r = s[0]; for (i = 1; i < 4; i++) { ushort x = s[i]; r = (ushort)(x > r ? x : r); } return (uint)r; }
CY_INLINE uint cy_umaxv_16_8(__m128i v) { ushort s[16 / sizeof(ushort)]; ushort r; int i; _mm_storeu_si128((__m128i *)s, v); r = s[0]; for (i = 1; i < 8; i++) { ushort x = s[i]; r = (ushort)(x > r ? x : r); } return (uint)r; }
CY_INLINE uint cy_uminv_8_8(__m128i v) { byte s[16 / sizeof(byte)]; byte r; int i; _mm_storeu_si128((__m128i *)s, v); r = s[0]; for (i = 1; i < 8; i++) { byte x = s[i]; r = (byte)(x < r ? x : r); } return (uint)r; }
CY_INLINE uint cy_uminv_8_16(__m128i v) { byte s[16 / sizeof(byte)]; byte r; int i; _mm_storeu_si128((__m128i *)s, v); r = s[0]; for (i = 1; i < 16; i++) { byte x = s[i]; r = (byte)(x < r ? x : r); } return (uint)r; }
CY_INLINE uint cy_uminv_16_4(__m128i v) { ushort s[16 / sizeof(ushort)]; ushort r; int i; _mm_storeu_si128((__m128i *)s, v); r = s[0]; for (i = 1; i < 4; i++) { ushort x = s[i]; r = (ushort)(x < r ? x : r); } return (uint)r; }
CY_INLINE uint cy_uminv_16_8(__m128i v) { ushort s[16 / sizeof(ushort)]; ushort r; int i; _mm_storeu_si128((__m128i *)s, v); r = s[0]; for (i = 1; i < 8; i++) { ushort x = s[i]; r = (ushort)(x < r ? x : r); } return (uint)r; }
CY_INLINE uint cy_smaxv_8_8(__m128i v) { byte s[16 / sizeof(byte)]; byte r; int i; _mm_storeu_si128((__m128i *)s, v); r = s[0]; for (i = 1; i < 8; i++) { byte x = s[i]; r = (byte)((signed char)x > (signed char)r ? x : r); } return (uint)r; }
CY_INLINE uint cy_smaxv_8_16(__m128i v) { byte s[16 / sizeof(byte)]; byte r; int i; _mm_storeu_si128((__m128i *)s, v); r = s[0]; for (i = 1; i < 16; i++) { byte x = s[i]; r = (byte)((signed char)x > (signed char)r ? x : r); } return (uint)r; }
CY_INLINE uint cy_smaxv_16_4(__m128i v) { ushort s[16 / sizeof(ushort)]; ushort r; int i; _mm_storeu_si128((__m128i *)s, v); r = s[0]; for (i = 1; i < 4; i++) { ushort x = s[i]; r = (ushort)((short)x > (short)r ? x : r); } return (uint)r; }
CY_INLINE uint cy_smaxv_16_8(__m128i v) { ushort s[16 / sizeof(ushort)]; ushort r; int i; _mm_storeu_si128((__m128i *)s, v); r = s[0]; for (i = 1; i < 8; i++) { ushort x = s[i]; r = (ushort)((short)x > (short)r ? x : r); } return (uint)r; }
CY_INLINE uint cy_sminv_8_8(__m128i v) { byte s[16 / sizeof(byte)]; byte r; int i; _mm_storeu_si128((__m128i *)s, v); r = s[0]; for (i = 1; i < 8; i++) { byte x = s[i]; r = (byte)((signed char)x < (signed char)r ? x : r); } return (uint)r; }
CY_INLINE uint cy_sminv_8_16(__m128i v) { byte s[16 / sizeof(byte)]; byte r; int i; _mm_storeu_si128((__m128i *)s, v); r = s[0]; for (i = 1; i < 16; i++) { byte x = s[i]; r = (byte)((signed char)x < (signed char)r ? x : r); } return (uint)r; }
CY_INLINE uint cy_sminv_16_4(__m128i v) { ushort s[16 / sizeof(ushort)]; ushort r; int i; _mm_storeu_si128((__m128i *)s, v); r = s[0]; for (i = 1; i < 4; i++) { ushort x = s[i]; r = (ushort)((short)x < (short)r ? x : r); } return (uint)r; }
CY_INLINE uint cy_sminv_16_8(__m128i v) { ushort s[16 / sizeof(ushort)]; ushort r; int i; _mm_storeu_si128((__m128i *)s, v); r = s[0]; for (i = 1; i < 8; i++) { ushort x = s[i]; r = (ushort)((short)x < (short)r ? x : r); } return (uint)r; }
CY_INLINE __m128i cy_rev64_8(__m128i v) { byte s[16], r[16]; int i, k; _mm_storeu_si128((__m128i *)s, v); for (i = 0; i < 16; i += 8) for (k = 0; k < 8; k += 1) memcpy(r + i + k, s + i + 8 - 1 - k, 1); return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_rev64_16(__m128i v) { byte s[16], r[16]; int i, k; _mm_storeu_si128((__m128i *)s, v); for (i = 0; i < 16; i += 8) for (k = 0; k < 8; k += 2) memcpy(r + i + k, s + i + 8 - 2 - k, 2); return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_rev64_32(__m128i v) { byte s[16], r[16]; int i, k; _mm_storeu_si128((__m128i *)s, v); for (i = 0; i < 16; i += 8) for (k = 0; k < 8; k += 4) memcpy(r + i + k, s + i + 8 - 4 - k, 4); return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_rev32_8(__m128i v) { byte s[16], r[16]; int i, k; _mm_storeu_si128((__m128i *)s, v); for (i = 0; i < 16; i += 4) for (k = 0; k < 4; k += 1) memcpy(r + i + k, s + i + 4 - 1 - k, 1); return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_rev32_16(__m128i v) { byte s[16], r[16]; int i, k; _mm_storeu_si128((__m128i *)s, v); for (i = 0; i < 16; i += 4) for (k = 0; k < 4; k += 2) memcpy(r + i + k, s + i + 4 - 2 - k, 2); return _mm_loadu_si128((__m128i *)r); }
CY_INLINE __m128i cy_rev16_8(__m128i v) { byte s[16], r[16]; int i, k; _mm_storeu_si128((__m128i *)s, v); for (i = 0; i < 16; i += 2) for (k = 0; k < 2; k += 1) memcpy(r + i + k, s + i + 2 - 1 - k, 1); return _mm_loadu_si128((__m128i *)r); }
CY_INLINE ulonglong cy_system_register(void) { return 0; }
CY_INLINE double cy_faddp_pd(__m128d v) { return _mm_cvtsd_f64(_mm_add_sd(v, _mm_unpackhi_pd(v, v))); }
CY_INLINE float cy_faddp_ps(__m128 v) { return _mm_cvtss_f32(_mm_add_ss(v, _mm_shuffle_ps(v, v, 0x55))); }
'''


# cy_* helpers taking vectors: the SSE type of each argument (None = scalar).
HELPER_ARGS = {'cy_bits32': ('__m128',), 'cy_bits64': ('__m128d',), 'cy_addv_epi32': ('__m128i',),
               'cy_addv_epi64': ('__m128i',), 'cy_maxv_epi32': ('__m128i',), 'cy_minv_epi32': ('__m128i',),
               'cy_maxv_epu32': ('__m128i',), 'cy_minv_epu32': ('__m128i',), 'cy_faddp_pd': ('__m128d',),
               'cy_faddp_ps': ('__m128',), 'cy_cnt_epi8': ('__m128i',), 'cy_addv_epu8_8': ('__m128i',),
               'cy_addv_epu8_16': ('__m128i',)}


# cy_* helpers working on whole vectors (__m128i in, __m128i or a scalar out).
VECTOR_HELPERS = ('cy_addp_', 'cy_umaxp_', 'cy_uminp_', 'cy_smaxp_', 'cy_sminp_', 'cy_shrn_', 'cy_rshrn_',
                  'cy_rev64_', 'cy_rev32_', 'cy_rev16_', 'cy_addv_', 'cy_umaxv_', 'cy_uminv_', 'cy_smaxv_',
                  'cy_sminv_', 'cy_maxv_', 'cy_minv_', 'cy_cnt_')


def is_fpreg(name):
    """Floating-point / SIMD register variables: xmmN (x86) and vN (AArch64)."""
    return name.startswith('xmm') or (name[:1] == 'v' and name[1:].split('_')[0].isdigit())


def c_identifier(name):
    text = re.sub(r'[^A-Za-z0-9_]', '_', name.replace('::', '__').replace('~', 'dtor_'))
    return text if text and not text[0].isdigit() else '_' + text


class VarInfo:
    def __init__(self, name, size):
        self.name = name
        self.c_name = name
        self.size = size
        self.signed_votes = 0
        self.unsigned_votes = 0
        self.pointer = False
        self.float = False
        self.param_index = None
        self.memory = False
        self.vector = None

    @property
    def signed(self):
        return self.signed_votes > self.unsigned_votes

    def ctype(self, word):
        if self.vector:
            return self.vector
        if self.float:
            return 'float' if self.size == 4 else 'double'
        if self.pointer:
            return 'byte *'
        return INT_NAMES.get((self.size, self.signed), 'ulonglong' if self.size > 8 else 'uint')


class Generator:
    def __init__(self, program, name, word, names_by_address=None, strict=False, arity=None, loose_calls=()):
        # strict: output meant to compile as a module; imports go through their import pointer
        # (__imp_X, no clash with CRT headers) and are collected in self.imports.
        self.strict = strict
        self.arity = arity or {}     # callee address -> parameter count of its printed prototype
        self.loose_calls = loose_calls   # callees whose prototype was not stable: called unprototyped
        self.imports = set()
        self.global_names = {}    # address -> C name of the globals used
        self.code_refs = {}       # address -> C name of the functions called or referenced
        self.p = program
        self.name = name
        self.word = word
        self.names_by_address = names_by_address or {}
        self.vars = {}

    # ------------------------------------------------------------------ preparation

    def statements(self):
        for b in self.p.order:
            for i, s in enumerate(self.p.blocks[b]):
                yield b, i, s

    def narrow(self):
        """Variables only ever written as zext(x32) and read as trunc(.., 4) become 32-bit."""
        defs, uses = {}, {}
        for b, i, s in self.statements():
            if isinstance(s, Assign):
                defs.setdefault(s.dst.name, []).append(s.src)
            for expr in s.exprs():
                self._collect_uses(expr, uses, None)
        params = set(self.p.live_in)
        changed = {}
        all_names = set(defs) | set(uses)
        for name in all_names:
            use_sizes = uses.get(name, [])
            if not use_sizes or any(u is None for u in use_sizes):
                continue
            target = max(use_sizes)
            def_sizes = [value_size(d) for d in defs.get(name, [])]
            if name in params and not defs.get(name):
                def_sizes = []
            if def_sizes and max(def_sizes) > target:
                continue
            size = max([target] + def_sizes)
            current = self.var_size(name)
            if size < current:
                changed[name] = size
        if not changed:
            return
        for b in self.p.order:
            rewritten = []
            for s in self.p.blocks[b]:
                s = s.map_exprs(lambda e: self._narrow_expr(e, changed))
                if isinstance(s, Assign) and s.dst.name in changed:
                    size = changed[s.dst.name]
                    src = s.src
                    if isinstance(src, Cast) and src.kind == 'zext' and src.a.size == size:
                        src = src.a
                    elif src.size != size:
                        src = Cast('trunc', src, size)
                    s = Assign(Var(s.dst.name, size), src, s.address)
                rewritten.append(s)
            self.p.blocks[b] = rewritten

    def var_size(self, name):
        for b, i, s in self.statements():
            if isinstance(s, Assign) and s.dst.name == name:
                return s.dst.size
            for expr in s.exprs():
                for node in expr.walk():
                    if isinstance(node, Var) and node.name == name:
                        return node.size
        return self.word

    def _collect_uses(self, expr, uses, parent):
        if isinstance(expr, Var):
            uses.setdefault(expr.name, []).append(parent.size if isinstance(parent, Cast) and parent.kind == 'trunc'
                                                  else None)
            return
        for kid in expr.kids():
            self._collect_uses(kid, uses, expr)

    def _narrow_expr(self, expr, changed):
        if isinstance(expr, Cast) and expr.kind == 'trunc' and isinstance(expr.a, Var) and expr.a.name in changed:
            size = changed[expr.a.name]
            var = Var(expr.a.name, size)
            return var if expr.size == size else Cast('trunc', var, expr.size)
        if isinstance(expr, Var) and expr.name in changed:
            return Var(expr.name, changed[expr.name])
        kids = expr.kids()
        if not kids:
            return expr
        new = [self._narrow_expr(k, changed) for k in kids]
        return expr.rebuild(new) if any(a is not b for a, b in zip(new, kids)) else expr

    def info(self, name, size):
        if name not in self.vars:
            self.vars[name] = VarInfo(name, size)
        v = self.vars[name]
        v.size = max(v.size, size) if not v.float else v.size
        return v

    def infer(self):
        for b, i, s in self.statements():
            if isinstance(s, Assign):
                v = self.info(s.dst.name, s.dst.size)
                if is_float_expr(s.src) or is_fpreg(s.dst.name):
                    v.float = True
                    v.size = s.src.size if s.src.size in (4, 8) else 8
                if isinstance(s.src, Cast) and s.src.kind == 'sext':
                    v.signed_votes += 1
                kind = vector_kind(s.src)
                if kind:
                    v.vector = kind
            for expr in s.exprs():
                for node in expr.walk():
                    if isinstance(node, Var):
                        self.info(node.name, node.size)
                    if isinstance(node, Load) or isinstance(node, Store):
                        self.mark_pointer(node.addr)
                    if isinstance(node, Cmp) and not node.op.endswith('f'):
                        for side in (node.a, node.b):
                            if isinstance(side, Var):
                                if node.op.endswith('s'):
                                    self.info(side.name, side.size).signed_votes += 1
                                elif node.op.endswith('u'):
                                    self.info(side.name, side.size).unsigned_votes += 1
                    if isinstance(node, Bin) and isinstance(node.a, Var):
                        if node.op in ('>>s', '/s', '%s'):
                            self.info(node.a.name, node.a.size).signed_votes += 1
                        elif node.op in ('>>u', '/u', '%u'):
                            self.info(node.a.name, node.a.size).unsigned_votes += 1
            if isinstance(s, Store):
                self.mark_pointer(s.addr)
        # Floating-point parameters: float when every scalar use is 4 bytes wide, else double.
        widths = {}
        for b, i, s in self.statements():
            # Copies between xmm registers and 4 / 8-byte variables (movsd / movss) are floats.
            if isinstance(s, Assign) and isinstance(s.src, Var):
                if is_fpreg(s.dst.name) and s.src.size in (4, 8) and not is_fpreg(s.src.name):
                    widths.setdefault(s.src.name, set()).add(s.src.size)
                elif is_fpreg(s.src.name) and s.dst.size in (4, 8) and not is_fpreg(s.dst.name):
                    widths.setdefault(s.dst.name, set()).add(s.dst.size)
                    widths.setdefault(s.src.name, set()).add(s.dst.size)    # str s0 / movss: a float
        self.int_used = set()
        for b, i, s in self.statements():
            for expr in s.exprs():
                for node in expr.walk():
                    if isinstance(node, (Bin, Cmp)) and not node.op.endswith('f') or                             isinstance(node, Cast) and node.kind in ('zext', 'sext', 'trunc', 'i2f'):
                        for side in node.kids():
                            if isinstance(side, Var):
                                self.int_used.add(side.name)
        for b, i, s in self.statements():
            for expr in s.exprs():
                for node in expr.walk():
                    if isinstance(node, Bin) and node.op.endswith('f'):
                        sides, width = (node.a, node.b), node.size
                    elif isinstance(node, Cmp) and node.op.endswith('f'):
                        sides, width = (node.a, node.b), node.operand_size
                    elif isinstance(node, Cast) and node.kind == 'f2f':
                        sides, width = (node.a,), 4 if node.size == 8 else 8
                    elif isinstance(node, Cast) and node.kind == 'f2i' and node.a.size in (4, 8):
                        sides, width = (node.a,), node.a.size
                    elif isinstance(node, Intrinsic) and node.name.startswith('_mm_') and \
                            node.name.endswith(('_ps', '_pd', '_ss', '_sd')) and \
                            not node.name.startswith(('_mm_set', '_mm_cast', '_mm_storeu', '_mm_loadu')):
                        sides = [arg for arg in node.args if isinstance(arg, Var) and arg.size in (4, 8)]
                        for side in sides:
                            widths.setdefault(side.name, set()).add(side.size)
                        continue
                    elif isinstance(node, Intrinsic) and node.name in FLOAT_FUNCTIONS and node.size in (4, 8) and \
                            not node.name.startswith('cy_'):
                        sides, width = node.args, node.size
                    else:
                        continue
                    for side in sides:
                        if isinstance(side, Var):
                            widths.setdefault(side.name, set()).add(width)
        for name, sizes in widths.items():
            # A variable only ever used as a floating-point operand (stack parameter or slot
            # loaded with movsd/fld) is a float / double.
            v = self.vars.get(name)
            if v is not None and not v.pointer and not v.vector and not v.float and v.size in (4, 8) and                     name not in self.int_used:
                v.float = True
                v.size = 4 if sizes == {4} else 8
        for name in self.p.live_in:
            if name in self.vars and is_fpreg(name):
                v = self.vars[name]
                v.float = True
                if not v.vector:
                    v.size = 4 if widths.get(name) == {4} else 8
        self.propagate_float_types(widths)

    def propagate_float_types(self, widths):
        """Plain copies (a = b) share a type: one floating-point member makes the whole group
        floating point, as do returned values of a float function and arguments passed to a
        callee's float parameters."""
        parent = {}

        def find(x):
            while parent.setdefault(x, x) != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        seeds = set()
        for b, i, s in self.statements():
            if isinstance(s, Assign) and isinstance(s.src, Var) and s.src.size == s.dst.size:
                parent[find(s.dst.name)] = find(s.src.name)
            if isinstance(s, Ret) and isinstance(s.value, Var) and getattr(self.p, 'float_return', 0):
                seeds.add(s.value.name)
            for expr in s.exprs():
                for node in expr.walk():
                    if isinstance(node, Call) and node.hints:
                        seeds.update(arg.name for arg, is_float in zip(node.args, node.hints)
                                     if is_float and isinstance(arg, Var))
        seeds.update(name for name, v in self.vars.items() if v.float and not v.vector)
        floating = {find(name) for name in seeds}
        for name, v in self.vars.items():
            if not v.float and not v.vector and not v.pointer and v.size in (4, 8) and \
                    find(name) in floating and name not in self.int_used:
                v.float = True
        # Copies also share the width: a group used as `float` anywhere is float.
        single = {find(name) for name, sizes in widths.items() if sizes == {4}}
        for name, v in self.vars.items():
            if v.float and not v.vector and find(name) in single:
                v.size = 4

    def mark_pointer(self, addr):
        base = addr
        while isinstance(base, Bin) and base.op in ('+', '-'):
            if isinstance(base.a, Var) and base.a.size == self.word:
                base = base.a
                break
            base = base.a
        if isinstance(base, Var) and base.size == self.word and base.name in self.vars:
            self.vars[base.name].pointer = True

    def reads_input(self, name):
        """False when the entry value of a register only survives a partial write (`mov cl, 3`
        gives `ecx & 0xffffff00 | 3`): its upper bits are not a real input."""
        total = merged = 0
        for b, i, s in self.statements():
            for expr in s.exprs():
                for e in expr.walk():
                    if isinstance(e, Var) and e.name == name:
                        total += 1
                    elif isinstance(e, Bin) and e.op == '&' and isinstance(e.a, Var) and e.a.name == name                             and isinstance(e.b, Const) and isinstance(e.b.value, int) and not e.b.value & 0xff:
                        merged += 1
        return total > merged

    def assign_names(self):
        f = self.p.f
        params = []
        float_from = None
        if f.convention == 'aapcs64':
            # Integer registers x0.. then floating-point registers v0..: prototypes list the
            # integer parameters first (callers order their arguments the same way).
            ints = {f.args.index(n) + 1: n for n in self.p.live_in if n in f.args and n in self.vars}
            floats = {f.fargs.index(n) + 1: n for n in self.p.live_in if n in f.fargs and n in self.vars}
            float_from = max(ints, default=0)
            params = [(index, 0, name) for index, name in ints.items()] + \
                [(float_from + index, 1, name) for index, name in floats.items()]
        for name in self.p.live_in if f.convention != 'aapcs64' else ():
            if name in f.args:
                params.append((f.args.index(name) + 1, 0, name))
            elif name in f.fargs and self.vars.get(name) is not None and self.vars[name].float:
                params.append((f.fargs.index(name) + 1, 1, name))
            elif name.startswith('param_'):
                params.append((int(name.split('_')[1].split('_')[0]), 0, name))
        params = [(index, name) for index, _, name in sorted(params)]
        used_params = {}
        for index, name in params:
            if name in self.vars:
                used_params.setdefault(index, name)
        self.param_list = []
        # Stack slots each parameter takes (x86: a double or long long spans two 4-byte slots).
        self.param_sizes = []
        if used_params:
            index = 1
            while index <= max(used_params):
                name = used_params.get(index)
                if name:
                    v = self.vars[name]
                    v.c_name = 'param_%d' % index
                    v.param_index = index
                    self.param_list.append(v)
                    wide = f.convention == 'x86' and v.size == 8 and index + 1 not in used_params
                    self.param_sizes.append(8 if wide else self.word)
                    index += 2 if wide else 1
                else:
                    dummy = VarInfo('unused_%d' % index, self.word)
                    dummy.c_name = 'param_%d' % index
                    if float_from is not None and index > float_from:
                        dummy.float = True
                    self.param_list.append(dummy)
                    self.param_sizes.append(self.word)
                    index += 1
        self.stack_param_count = len(self.param_list)
        self.register_params = []
        if f.convention == 'x86':
            # Non-standard register inputs (compiler helpers) become trailing parameters; callers
            # pass them in the same order (see lifter.callee_signature).
            from .lifter import X86_REGISTER_ARGS
            for register in X86_REGISTER_ARGS:
                if register in self.p.live_in and register in self.vars and self.reads_input(register):
                    v = self.vars[register]
                    v.c_name = 'param_' + register
                    v.param_index = 100 + len(self.register_params)
                    self.param_list.append(v)
                    self.register_params.append(register)
        counters = {}
        for name, v in self.vars.items():
            if v.param_index is not None:
                continue
            if name.startswith(('local_', 'home_')):
                base = name.split('_')
                v.c_name = '%s_%s' % (base[0], base[1]) + ('_%s' % base[2] if len(base) > 2 else '')
                continue
            if name in self.p.live_in:
                v.c_name = 'in_' + name.upper()
                continue
            if v.vector:
                counters['auVar'] = counters.get('auVar', 0) + 1
                v.c_name = 'auVar%d' % counters['auVar']
                continue
            prefix = 'f' if v.float and v.size == 4 else 'd' if v.float else 'p' if v.pointer else \
                PREFIX.get((v.size, v.signed), 'u')
            counters[prefix] = counters.get(prefix, 0) + 1
            v.c_name = '%sVar%d' % (prefix, counters[prefix])

    # ------------------------------------------------------------------ printing

    def label(self, block):
        return 'LAB_%x' % block

    def vtype(self, name):
        v = self.vars.get(name)
        return v

    def expr(self, e, prec=99):
        text, p = self.render(e)
        return '(%s)' % text if p > prec else text

    def const_text(self, value, size, want_signed=True):
        s = signed(value, size) if want_signed else value
        if -0x1000 < s < 0x1000:
            return str(s) if size <= 4 else ('%dLL' % s if abs(s) > 0x7fffffff else str(s))
        if s < 0 and want_signed:
            return '-0x%x' % -s
        suffix = 'ULL' if size == 8 else ('U' if value > 0x7fffffff else '')
        return '0x%x%s' % (value & mask(size), suffix)

    def typed(self, e, want_signed, size):
        """Operand text with the signedness required by the operator."""
        if isinstance(e, Const):
            return self.const_text(e.value, size, want_signed), 0
        current = self.signedness(e)
        text, p = self.render(e)
        if current is not None and current == want_signed and (e.size == size or self.is_bool(e)):
            return text, p
        type_name = INT_NAMES.get((size, want_signed), 'ulonglong')
        return '(%s)%s' % (type_name, text if p <= 1 else '(%s)' % text), 1

    def signedness(self, e):
        if isinstance(e, Var):
            v = self.vars.get(e.name)
            if v is None or v.pointer or v.float:
                return None
            return v.signed if v.size == e.size else None
        if isinstance(e, Cast):
            if e.kind == 'sext':
                return True
            if e.kind in ('zext', 'trunc', 'f2i'):
                return None
        if isinstance(e, (Cmp, Logic)):
            return None
        return None

    @staticmethod
    def is_bool(e):
        return isinstance(e, (Cmp, Logic)) or (isinstance(e, Cast) and isinstance(e.a, (Cmp, Logic)))

    def is_pointer(self, e):
        if isinstance(e, Var):
            v = self.vars.get(e.name)
            return bool(v and v.pointer)
        if isinstance(e, Bin) and e.op in ('+', '-'):
            if e.op == '+' and self.is_pointer(e.b):
                return True
            return self.is_pointer(e.a) and not self.is_pointer(e.b)
        if isinstance(e, Sym):
            return e.kind in ('data', 'rodata', 'string')
        return isinstance(e, Addr)

    def note_access(self, addr, size):
        """Record how far into a global the code reads or writes (for its definition)."""
        base, delta = addr, 0
        if isinstance(addr, Bin) and addr.op == '+' and isinstance(addr.b, Const):
            base, delta = addr.a, addr.b.value
        if isinstance(base, Bin) and base.op == '+':
            # Indexed access: the extent is unknown; reserve a generous area.
            for side in (base.a, base.b):
                if isinstance(side, Sym) and side.kind in ('data', 'rodata'):
                    self.globals[side.address] = max(self.globals.get(side.address, 0), 0x400)
            return
        if isinstance(base, Sym) and base.kind in ('data', 'rodata'):
            self.globals[base.address] = max(self.globals.get(base.address, 0), delta + size)

    def render(self, e):
        if isinstance(e, Const):
            return self.const_text(e.value, e.size), 0 if e.value < 0x80000000 else 1
        if isinstance(e, FConst):
            value = float(e.value)
            if value != value:
                return 'NAN', 0
            if value in (float('inf'), float('-inf')):
                return ('INFINITY' if value > 0 else '-INFINITY'), 0 if value > 0 else 1
            text = repr(value)
            if e.size == 4:
                text += 'f'
            return text, 0 if not text.startswith('-') else 1
        if isinstance(e, Var):
            v = self.vars.get(e.name)
            name = v.c_name if v else e.name
            if v and v.size != e.size and not v.float:
                return '(%s)%s' % (INT_NAMES.get((e.size, False), 'ulonglong'), name), 1
            return name, 0
        if isinstance(e, Addr):
            if e.name.startswith('stack'):
                return self.stack_ref(int(e.name[5:]))
            return '&' + e.name, 1
        if isinstance(e, Sym) and self.strict and e.kind in ('import', 'iat'):
            name = c_identifier(e.name.lstrip('&'))
            self.imports.add(name)
            return ('&__imp_' if e.kind == 'iat' else '__imp_') + name, 0
        if isinstance(e, Sym):
            if e.kind == 'string':
                return '(byte *)%s' % c_string(e.name), 1
            if e.kind in ('data', 'rodata'):
                self.globals[e.address] = max(self.globals.get(e.address, 1), 1)
                self.global_names[e.address] = c_identifier(e.name)
                return self.global_names[e.address], 0
            if e.kind == 'code':
                self.code_refs[e.address] = c_identifier(e.name)
            return c_identifier(e.name), 0
        if isinstance(e, Load):
            type_name = self.load_type(e)
            self.note_access(e.addr, e.size)
            addr = self.address_text(e.addr)
            return '*(%s *)%s' % (type_name, addr), 1
        if isinstance(e, Bin):
            return self.render_bin(e)
        if isinstance(e, Un):
            inner = self.expr(e.a, 1)
            if self.kind_of(e.a) in ('__m128i', '__m128', '__m128d') and e.size in (4, 8):
                inner = '(%s)' % self.as_scalar(e.a, e.size)[0]
            op = {'neg': '-', 'not': '~', 'lnot': '!'}[e.op]
            if op in ('-', '~') and self.is_pointer(e.a):
                inner = '(%s)%s' % ('ulonglong' if self.word == 8 else 'uint', inner)
            if e.size < 4 and op in ('-', '~'):
                return '(%s)%s%s' % (INT_NAMES[(e.size, False)], op, inner), 1
            return op + inner, 1
        if isinstance(e, Cast):
            return self.render_cast(e)
        if isinstance(e, Cmp):
            return self.render_cmp(e)
        if isinstance(e, Logic):
            if e.op == 'not':
                return '!' + self.expr(e.a, 1), 1
            prec = PRECEDENCE[e.op]
            return '%s %s %s' % (self.expr(e.a, prec), e.op, self.expr(e.b, prec - 1)), prec
        if isinstance(e, Tern):
            a, b = self.expr(e.a, 12), self.expr(e.b, 12)
            if self.is_pointer(e.a) != self.is_pointer(e.b):
                integer = 'ulonglong' if self.word == 8 else 'uint'
                if self.is_pointer(e.a):
                    a = '(%s)%s' % (integer, self.expr(e.a, 1))
                else:
                    b = '(%s)%s' % (integer, self.expr(e.b, 1))
            return '%s ? %s : %s' % (self.expr(e.c, 12), a, b), 13
        if isinstance(e, Call):
            target = e.target
            if e.float and not (isinstance(target, Sym) and target.kind == 'code'):
                # Unknown callee read as returning a floating-point value.
                kind = 'double' if e.float == 8 else 'float'
                name = '((%s (*)())%s)' % (kind, self.expr(target, 1) if not isinstance(target, Sym) or
                                           self.strict else c_identifier(target.name))
            elif isinstance(target, Sym) and self.strict and target.kind == 'import':
                name = self.expr(target, 0)[0]
            elif isinstance(target, Sym):
                name = c_identifier(target.name)
                if target.kind == 'code':
                    self.code_refs[target.address] = name
            else:
                name = '((code *)%s)' % self.expr(target, 1)
            args = [self.call_arg(a) for a in e.args]
            address = getattr(target, 'address', None) if isinstance(target, Sym) else None
            if address is not None and address in self.loose_calls:
                return '((%s (*)())%s)(%s)' % ('double' if e.float == 8 else 'float' if e.float == 4 else 'ulonglong',
                                              name, ', '.join(args)), 0
            count = self.arity.get(address) if address is not None else None
            if count is not None:
                args = args[:count] + ['0'] * (count - len(args))
            return '%s(%s)' % (name, ', '.join(args)), 0
        if isinstance(e, Intrinsic):
            return self.render_intrinsic(e), 0
        if isinstance(e, Cond):
            return '__condition_%s()' % e.cc, 0
        if isinstance(e, Flags):
            return '__flags(%s, %s)' % (self.expr(e.a, 13), self.expr(e.b, 13)), 0
        return '/* ? */0', 0

    def kind_of(self, e):
        """'__m128i' / '__m128' / '__m128d' for vectors, 'float'/'double' for scalars, None otherwise."""
        if isinstance(e, Var):
            v = self.vars.get(e.name)
            if v is not None and v.vector:
                return v.vector
            if v is not None and v.float:
                return 'float' if v.size == 4 else 'double'
            return None
        kind = vector_kind(e)
        if kind:
            return kind
        if is_float_expr(e):
            return 'float' if e.size == 4 else 'double'
        return None

    def as_vector(self, e, want):
        if isinstance(e, (FConst, Const)) and e.value == 0:
            return {'__m128i': '_mm_setzero_si128()', '__m128': '_mm_setzero_ps()', '__m128d': '_mm_setzero_pd()'}[want]
        text = self.expr(e, 13)
        have = self.kind_of(e)
        if have == want or have is None:
            return text
        if have == 'float':
            text = '_mm_set_ss(%s)' % text
            have = '__m128'
        elif have == 'double':
            text = '_mm_set_sd(%s)' % text
            have = '__m128d'
        if have == want:
            return text
        casts = {('__m128i', '__m128'): '_mm_castsi128_ps', ('__m128', '__m128i'): '_mm_castps_si128',
                 ('__m128d', '__m128i'): '_mm_castpd_si128', ('__m128i', '__m128d'): '_mm_castsi128_pd',
                 ('__m128', '__m128d'): '_mm_castps_pd', ('__m128d', '__m128'): '_mm_castpd_ps'}
        return '%s(%s)' % (casts[(have, want)], text)

    def call_arg(self, e):
        """An xmm register passed to a call carries a float or a double, not a vector."""
        kind = self.kind_of(e)
        if kind in ('__m128', '__m128d', '__m128i'):
            return self.as_scalar(e, 4 if kind == '__m128' else 8)[0]
        return self.expr(e, 13)

    def as_scalar(self, e, size):
        """Scalar float view of an expression that may hold a vector (xmm register reuse)."""
        have = self.kind_of(e)
        if have in ('__m128i', '__m128', '__m128d'):
            vector = self.as_vector(e, '__m128' if size == 4 else '__m128d')
            return '%s(%s)' % ('_mm_cvtss_f32' if size == 4 else '_mm_cvtsd_f64', vector), 0
        return self.expr(e, 1), 0

    def render_intrinsic(self, e):
        name = e.name
        if name.startswith(VECTOR_HELPERS) and name not in HELPER_ARGS:
            return '%s(%s)' % (name, ', '.join(self.as_vector(arg, '__m128i') if arg.size == 16 or
                                               self.kind_of(arg) in ('__m128i', '__m128', '__m128d', 'float', 'double')
                                               else self.expr(arg, 13) for arg in e.args))
        if name in HELPER_ARGS:
            kinds = HELPER_ARGS[name]
            return '%s(%s)' % (name, ', '.join(self.as_vector(arg, kinds[i]) if kinds[i] else self.expr(arg, 13)
                                               for i, arg in enumerate(e.args)))
        if not name.startswith('_mm_'):
            vectors = ('__m128i', '__m128', '__m128d')
            return '%s(%s)' % (name, ', '.join(self.as_scalar(a, e.size if e.size in (4, 8) else 8)[0]
                                               if self.kind_of(a) in vectors else self.expr(a, 13)
                                               for a in e.args))
        want = '__m128' if name.endswith('_ps') else '__m128d' if name.endswith('_pd') else '__m128i'
        args = []
        for index, arg in enumerate(e.args):
            if name.startswith(('_mm_loadu_', '_mm_storeu_', '_mm_loadl_', '_mm_storel_')) and index == 0:
                pointer = {'__m128i': '__m128i', '__m128': 'float', '__m128d': 'double'}[want]
                args.append('(%s *)%s' % (pointer, self.address_text(arg)))
            elif not name.startswith(('_mm_set', '_mm_insert')) and                     (isinstance(arg, FConst) or isinstance(arg, Const) and (arg.size == 16 or name.startswith('_mm_store'))):
                args.append(self.as_vector(arg, want))
            elif isinstance(arg, (Const, FConst)) or name.startswith(('_mm_set_', '_mm_setr_', '_mm_set1_')) or \
                    name in ('_mm_cvtsi32_si128', '_mm_cvtsi64_si128') or \
                    (name.startswith('_mm_insert_epi') and index == 1):
                args.append(self.expr(arg, 13))
            elif name in ('_mm_cvtsi128_si32', '_mm_cvtsi128_si64', '_mm_move_epi64', '_mm_storel_epi64',
                          '_mm_cvtepi32_ps', '_mm_cvtepi32_pd') or \
                    name.startswith(('_mm_extract_epi', '_mm_movemask_epi8', '_mm_cvtepi', '_mm_cvtepu')):
                args.append(self.as_vector(arg, '__m128i'))
            elif name in ('_mm_cvttps_epi32', '_mm_cvtps_epi32', '_mm_cvtps_pd', '_mm_extract_ps', '_mm_movemask_ps'):
                args.append(self.as_vector(arg, '__m128'))
            elif name in ('_mm_cvttpd_epi32', '_mm_cvtpd_ps', '_mm_movemask_pd'):
                args.append(self.as_vector(arg, '__m128d'))
            else:
                args.append(self.as_vector(arg, want))
        return '%s(%s)' % (name, ', '.join(args))

    def stack_ref(self, offset):
        """C text for the address of a stack location: a frame buffer (+ offset) or &variable."""
        regions = getattr(self.p.f, 'regions', {})
        for start, end in regions.items():
            if start <= offset < end:
                name = 'auStack_%x' % -start if start < 0 else 'auHome_%x' % start
                self.memory_slots[name] = end - start
                if offset == start:
                    return name, 0
                return '(%s + 0x%x)' % (name, offset - start), 0
        if offset < 0:
            name = 'auStack_%x' % -offset
            self.memory_slots[name] = max(self.memory_slots.get(name, 0), 0x40)
            return name, 0
        name = self.stack_param_name(offset)
        v = self.vars.get(name)
        if v is None:
            name = 'stack_%x' % offset
            self.memory_slots[name] = max(self.memory_slots.get(name, 0), 0x40)
            return name, 0
        return '(byte *)&%s' % v.c_name, 1

    def stack_param_name(self, offset):
        f = self.p.f
        if f.word == 4:
            return 'param_%d' % ((offset - 4) // 4 + 1)
        if offset <= 0x20 and f.convention == 'win64':
            return 'home_%x' % offset
        first = 0x28 if f.convention == 'win64' else 8
        return 'param_%d' % ((offset - first) // 8 + len(f.args) + 1)

    def load_type(self, e):
        if e.float:
            return 'float' if e.size == 4 else 'double'
        return INT_NAMES.get((e.size, False), 'byte')

    def address_text(self, addr):
        if isinstance(addr, Const):
            return '(byte *)0x%x' % addr.value
        if self.is_pointer(addr):
            return self.expr(addr, 1) if isinstance(addr, (Var, Addr)) else '(%s)' % self.expr(addr, 13)
        return '(byte *)(%s)' % self.expr(addr, 13) if not isinstance(addr, Var) else '(byte *)%s' % self.expr(addr, 1)

    def render_bin(self, e):
        op = e.op
        if op.endswith('f'):
            symbol = op[0]
            prec = PRECEDENCE[symbol]
            vectors = ('__m128i', '__m128', '__m128d')
            left = self.as_scalar(e.a, e.size)[0] if self.kind_of(e.a) in vectors else self.expr(e.a, prec)
            right = self.as_scalar(e.b, e.size)[0] if self.kind_of(e.b) in vectors else self.expr(e.b, prec - 1)
            return '%s %s %s' % (left, symbol, right), prec
        if op in ('>>s', '>>u', '/s', '/u', '%s', '%u'):
            want = op.endswith('s')
            symbol = op[:-1]
            prec = PRECEDENCE[symbol]
            left, lp = self.typed(e.a, want, e.size)
            if symbol == '>>':
                right, rp = self.expr(e.b, prec - 1), 0
            else:
                right, rp = self.typed(e.b, want, e.size)
            left = left if lp <= prec else '(%s)' % left
            right = right if rp < prec else '(%s)' % right
            text = '%s %s %s' % (left, symbol, right)
            if e.size < 4:
                return '(%s)(%s)' % (INT_NAMES[(e.size, want)], text), 1
            return text, prec
        symbol = op
        prec = PRECEDENCE.get(symbol, 4)
        a_pointer = self.is_pointer(e.a)
        left = self.expr(e.a, prec)
        right = self.expr(e.b, prec - 1)
        integer = 'ulonglong' if self.word == 8 else 'uint'
        # Pointers only take part in + and - (ptr + n, ptr - n, ptr - ptr); elsewhere they are integers.
        if a_pointer and symbol not in ('+', '-'):
            left = '(%s)%s' % (integer, self.expr(e.a, 1))
        if self.is_pointer(e.b) and (symbol != '-' or not a_pointer):
            right = '(%s)%s' % (integer, self.expr(e.b, 1))
        text = '%s %s %s' % (left, symbol, right)
        if e.size < 4:
            return '(%s)(%s)' % (INT_NAMES[(e.size, False)], text), 1
        return text, prec

    def render_cast(self, e):
        a = e.a
        if e.kind == 'trunc':
            return '(%s)%s' % (INT_NAMES.get((e.size, False), 'uint'), self.expr(a, 1)), 1
        if e.kind == 'zext':
            if self.is_bool(a):
                return '(%s)(%s)' % (INT_NAMES.get((e.size, False), 'uint'), self.expr(a, 13)), 1
            inner, _ = self.typed(a, False, a.size)
            return '(%s)%s' % (INT_NAMES.get((e.size, False), 'ulonglong'), inner if inner.startswith('(') or
                               inner.replace('_', 'a').isalnum() else '(%s)' % inner), 1
        if e.kind == 'sext':
            inner, _ = self.typed(a, True, a.size)
            return '(%s)%s' % (INT_NAMES.get((e.size, True), 'longlong'), inner if inner.startswith('(') or
                               inner.replace('_', 'a').isalnum() else '(%s)' % inner), 1
        if e.kind == 'i2f':
            inner, _ = self.typed(a, True, a.size)
            return '(%s)%s' % ('float' if e.size == 4 else 'double', inner if inner.startswith('(') else
                               '(%s)' % inner if ' ' in inner else inner), 1
        vectors = ('__m128i', '__m128', '__m128d')
        if e.kind == 'f2i':
            inner = '(%s)' % self.as_scalar(a, a.size if a.size in (4, 8) else 8)[0]                 if self.kind_of(a) in vectors else self.expr(a, 1)
            return '(%s)%s' % (INT_NAMES.get((e.size, True), 'int'), inner), 1
        if e.kind == 'f2f':
            inner = '(%s)' % self.as_scalar(a, 4 if e.size == 8 else 8)[0]                 if self.kind_of(a) in vectors else self.expr(a, 1)
            return '(%s)%s' % ('float' if e.size == 4 else 'double', inner), 1
        return self.render(a)

    def render_cmp(self, e):
        op = e.op
        if op.endswith('f'):
            symbol = op[:-1]
            prec = PRECEDENCE[symbol]
            vectors = ('__m128i', '__m128', '__m128d')
            size = e.operand_size if e.operand_size in (4, 8) else 8
            left = self.as_scalar(e.a, size)[0] if self.kind_of(e.a) in vectors else self.expr(e.a, prec)
            right = self.as_scalar(e.b, size)[0] if self.kind_of(e.b) in vectors else self.expr(e.b, prec - 1)
            return '%s %s %s' % (left, symbol, right), prec
        symbol = op.rstrip('su')
        prec = PRECEDENCE[symbol]
        if op in ('==', '!='):
            left = self.expr(e.a, prec)
            right = self.expr(e.b, prec - 1)
            if isinstance(e.b, Const) and self.is_pointer(e.a) and e.b.value == 0:
                right = '0'
            elif isinstance(e.b, Const):
                right = self.const_text(e.b.value, e.operand_size, True)
            return '%s %s %s' % (left, symbol, right), prec
        want = op.endswith('s')
        left, lp = self.typed(e.a, want, e.operand_size)
        right, rp = self.typed(e.b, want, e.operand_size)
        left = left if lp < prec else '(%s)' % left
        right = right if rp < prec else '(%s)' % right
        return '%s %s %s' % (left, symbol, right), prec

    def cond(self, e):
        return self.expr(e, 13)

    # ------------------------------------------------------------------ statements

    def statement_lines(self, block):
        lines = []
        for s in self.p.blocks[block]:
            if isinstance(s, (Branch, Ret, Switch)) or type(s).__name__ in ('Jump', 'IndirectJump'):
                continue
            if isinstance(s, Assign):
                v = self.vars.get(s.dst.name)
                target = v.c_name if v else s.dst.name
                value = self.expr(s.src, 14)
                if v and v.pointer and not self.is_pointer(s.src) and not isinstance(s.src, (Const, Call)):
                    value = '(byte *)(%s)' % value
                elif v and v.pointer and isinstance(s.src, Call):
                    value = '(byte *)%s' % value
                elif v and not v.pointer and not v.float and not v.vector and self.is_pointer(s.src):
                    value = '(%s)%s' % (v.ctype(self.word), self.expr(s.src, 1))
                if v and v.vector:
                    value = self.as_vector(s.src, v.vector)
                elif v and v.float and self.kind_of(s.src) in ('__m128i', '__m128', '__m128d'):
                    value = self.as_scalar(s.src, v.size)[0]
                lines.append('%s = %s;' % (target, value))
            elif isinstance(s, Store):
                self.note_access(s.addr, s.size)
                type_name = ('float' if s.size == 4 else 'double') if s.float or is_float_expr(s.value) \
                    else INT_NAMES.get((s.size, False), 'byte')
                value = self.expr(s.value, 14)
                if s.size == 16:
                    type_name = 'uint128'
                elif self.kind_of(s.value) in ('__m128i', '__m128', '__m128d'):
                    # Low lane of a vector register stored as a scalar (str d0 / movsd).
                    if type_name in ('float', 'double'):
                        value = self.as_scalar(s.value, s.size)[0]
                    elif s.size == 8:
                        value = '(ulonglong)_mm_cvtsi128_si64(%s)' % self.as_vector(s.value, '__m128i')
                    else:
                        value = '(%s)_mm_cvtsi128_si32(%s)' % (INT_NAMES.get((s.size, False), 'uint'),
                                                               self.as_vector(s.value, '__m128i'))
                lines.append('*(%s *)%s = %s;' % (type_name, self.address_text(s.addr), value))
            elif isinstance(s, ExprStmt):
                lines.append('%s;' % self.expr(s.expr, 14))
            elif isinstance(s, Comment):
                lines.append('/* %s */' % s.text.replace('*/', '* /'))
        return lines

    statements_for = statement_lines

    def ret(self, s):
        if s.value is None or not self.p.returns:
            return 'return;'
        value = s.value
        size = self.return_size
        if getattr(self.p, 'float_return', 0):
            from .ir import simplify
            if self.kind_of(value) in ('__m128i', '__m128', '__m128d'):
                return 'return %s;' % self.as_scalar(value, size)[0]
            return 'return %s;' % self.expr(simplify(value), 14)
        if value.size > size and not is_float_expr(value):
            value = Cast('trunc', value, size)
        from .ir import simplify
        return 'return %s;' % self.expr(simplify(value), 14)

    # ------------------------------------------------------------------ function

    def generate(self, calling_note=''):
        self.memory_slots = {}
        self.globals = {}
        self.narrow()
        self.infer()
        self.assign_names()
        self.return_size = self.p.return_size if self.p.returns else 0
        ret_info = None
        if self.p.returns:
            ret_var = None
            return_type = INT_NAMES.get((self.return_size, True), 'longlong')
            if self.return_is_float() or getattr(self.p, 'float_return', 0):
                return_type = 'double' if self.return_size == 8 else 'float'
        else:
            return_type = 'void'

        class Printer:
            pass
        printer = Printer()
        printer.statements = self.statement_lines
        printer.cond = self.cond
        printer.expr = lambda e: self.expr(e, 14)
        printer.ret = self.ret
        printer.label = self.label
        body = Structurer(self.p.order[0], self.p.blocks, self.p.succ, printer).run()
        entry = []
        param_texts = []
        for v in self.param_list:
            if v.vector and v.param_index is not None:
                # Callers pass a floating-point register as a double: rebuild the vector on entry.
                scalar = v.c_name + '_d'
                to_vector = {'__m128i': '_mm_castpd_si128', '__m128': '_mm_castpd_ps', '__m128d': ''}[v.vector]
                entry.append('  %s %s = %s(_mm_set_sd(%s));' % (v.vector, v.c_name, to_vector, scalar))
                param_texts.append('double ' + scalar)
            else:
                param_texts.append('%s %s' % (v.ctype(self.word), v.c_name))
        params = ', '.join(param_texts) or 'void'
        declarations = list(entry)
        by_type = {}
        for name, v in sorted(self.vars.items(), key=lambda item: item[1].c_name):
            if v.param_index is not None:
                continue
            if not any(v.c_name in line for line in body):
                continue
            by_type.setdefault(v.ctype(self.word), []).append(v.c_name)
        for type_name, names in sorted(by_type.items()):
            star = type_name.endswith('*')
            base = type_name[:-1].strip() if star else type_name
            declarations.append('  %s %s;' % (base, ', '.join(('*' if star else '') + n for n in sorted(names))))
        for slot, size in sorted(self.memory_slots.items(), key=lambda item: -int(item[0].split('_')[1], 16)):
            declarations.append('  byte %s[0x%x];' % (slot, size))
        header = '%s %s(%s)' % (return_type, c_identifier(self.name), params)
        lines = []
        if calling_note:
            lines.append('/* %s */' % calling_note)
        lines.append(header)
        lines.append('{')
        lines += declarations
        if declarations:
            lines.append('')
        lines += body
        lines.append('}')
        return '\n'.join(lines) + '\n'

    def return_is_float(self):
        for b, i, s in self.statements():
            if isinstance(s, Ret) and s.value is not None and is_float_expr(s.value):
                return True
        return False


def is_float_expr(e):
    if isinstance(e, FConst):
        return True
    if isinstance(e, Tern):
        return isinstance(e.c, Cmp) and e.c.op.endswith('f') and e.size in (4, 8) and \
            (is_float_expr(e.a) or is_float_expr(e.b) or e.c.a == e.a or e.c.b == e.a)
    if isinstance(e, Call):
        return bool(e.float)
    if isinstance(e, Load):
        return e.float
    if isinstance(e, Bin):
        return e.op.endswith('f')
    if isinstance(e, Cast):
        return e.kind in ('i2f', 'f2f')
    if isinstance(e, Var):
        return is_fpreg(e.name)
    if isinstance(e, Intrinsic):
        from .ir import FLOAT_FUNCTIONS
        return e.name in FLOAT_FUNCTIONS
    return False


def value_size(expr):
    if isinstance(expr, Cast) and expr.kind == 'zext':
        return expr.a.size
    return expr.size


def vector_kind(e):
    if isinstance(e, Intrinsic) and e.name.startswith(VECTOR_HELPERS) and e.size == 16:
        return '__m128i'
    if isinstance(e, Intrinsic) and e.name.startswith('_mm_') and e.size == 16:
        if e.name.endswith('_ps') or e.name in ('_mm_castsi128_ps', '_mm_castpd_ps', '_mm_set_ss'):
            return '__m128'
        if e.name.endswith('_pd') or e.name in ('_mm_castsi128_pd', '_mm_castps_pd', '_mm_set_sd'):
            return '__m128d'
        return '__m128i'
    return None


def c_string(text):
    return '"%s"' % text.encode('unicode_escape').decode('ascii').replace('"', '\\"')
