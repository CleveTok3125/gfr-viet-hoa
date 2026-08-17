"""Pure-Python XXH64 (little-endian, seed 0) matching xxhash.xxh64().intdigest().

Only the exact use-case needed by this project is implemented: hashing an
ASCII/UTF-8 path string with seed 0. Primes and constants follow the XXH64
spec (xxHash). Tested against the reference `xxhsum` vectors.
"""

PRIME64_1 = 0x9E3779B185EBCA87
PRIME64_2 = 0xC2B2AE3D27D4EB4F
PRIME64_3 = 0x165667B19E3779F9
PRIME64_4 = 0x85EBCA77C2B2AE63
PRIME64_5 = 0x27D4EB2F165667C5
MASK64 = (1 << 64) - 1


def _rotl(x, r):
    x &= MASK64
    return ((x << r) | (x >> (64 - r))) & MASK64


def xxh64(data: bytes, seed: int = 0) -> int:
    if isinstance(data, str):
        data = data.encode("utf-8")
    n = len(data)
    idx = 0

    if n >= 32:
        v1 = (seed + PRIME64_1 + PRIME64_2) & MASK64
        v2 = (seed + PRIME64_2) & MASK64
        v3 = seed & MASK64
        v4 = (seed - PRIME64_1) & MASK64

        while idx <= n - 32:
            v1 = (_rotl(v1 + ((int.from_bytes(data[idx:idx+8], "little") * PRIME64_2) & MASK64), 31) * PRIME64_1) & MASK64
            v2 = (_rotl(v2 + ((int.from_bytes(data[idx+8:idx+16], "little") * PRIME64_2) & MASK64), 31) * PRIME64_1) & MASK64
            v3 = (_rotl(v3 + ((int.from_bytes(data[idx+16:idx+24], "little") * PRIME64_2) & MASK64), 31) * PRIME64_1) & MASK64
            v4 = (_rotl(v4 + ((int.from_bytes(data[idx+24:idx+32], "little") * PRIME64_2) & MASK64), 31) * PRIME64_1) & MASK64
            idx += 32

        h = (_rotl(v1, 1) + _rotl(v2, 7) + _rotl(v3, 12) + _rotl(v4, 18)) & MASK64
        # merge round with v1..v4 (xxHash v0.8.x semantics:
        # val is rounded first, then acc = acc*PRIME64_1 + PRIME64_4)
        def _merge(acc, val):
            val = _round(0, val)
            acc ^= val
            return (acc * PRIME64_1 + PRIME64_4) & MASK64
        h = _merge(h, v1)
        h = _merge(h, v2)
        h = _merge(h, v3)
        h = _merge(h, v4)
    else:
        h = (seed + PRIME64_5) & MASK64

    h = (h + n) & MASK64

    while idx <= n - 8:
        k1 = _round(0, int.from_bytes(data[idx:idx+8], "little"))
        h = (h ^ k1) & MASK64
        h = (_rotl(h, 27) * PRIME64_1 + PRIME64_4) & MASK64
        idx += 8

    if idx <= n - 4:
        h = (h ^ ((int.from_bytes(data[idx:idx+4], "little") & 0xFFFFFFFF) * PRIME64_1)) & MASK64
        h = (_rotl(h, 23) * PRIME64_2 + PRIME64_3) & MASK64
        idx += 4

    while idx < n:
        h = (h ^ ((data[idx] & 0xFF) * PRIME64_5)) & MASK64
        h = (_rotl(h, 11) * PRIME64_1) & MASK64
        idx += 1

    def _avalanche(h):
        h = (h ^ (h >> 33)) & MASK64
        h = (h * PRIME64_2) & MASK64
        h = (h ^ (h >> 29)) & MASK64
        h = (h * PRIME64_3) & MASK64
        h = (h ^ (h >> 32)) & MASK64
        return h

    h = _avalanche(h)
    return h


def _round(acc, input_):
    acc = (acc + (input_ * PRIME64_2) & MASK64) & MASK64
    acc = _rotl(acc, 31)
    acc = (acc * PRIME64_1) & MASK64
    return acc


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vendor"))
    import xxhash as _c
    for s in ["", "a", "data/system/table/text/ko/text_ui.msg",
              "ui/campaign/gra/skill_skillinventory_01/campaign/kor/skill_skillinventory_01_t.tex"]:
        a = xxh64(s)
        b = _c.xxh64(s).intdigest()
        print(("OK " if a == b else "FAIL "), repr(s), hex(a), hex(b))
