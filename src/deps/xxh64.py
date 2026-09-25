"""XXH64 with a compiled-first backend: pip ``xxhash`` when importable,
otherwise the project's pure-Python ``vendor/xxh64_pure``.

``digest`` is the bulk-hashing entry point used to verify the persistent
scan-index cache: it prefers the compiled xxhash (GB/s) and falls back to
stdlib ``hashlib.sha256`` (C, zero deps) because the pure xxh64 is ~17 MB/s —
far too slow to re-hash the multi-MB cache inputs on every boot.
"""
import hashlib
from typing import Any

_xx: Any = None
try:
    import xxhash
    _xx = xxhash
except ImportError:
    pass

if _xx is not None:
    _COMPILED = True

    def xxh64(data, seed=0):
        """Return the xxh64 digest of ``data`` (bytes or str) as an int."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        return _xx.xxh64(data, seed=seed).intdigest()

    def digest(data):
        """Return a fast 64-bit digest of ``data`` (compiled xxh64)."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        return _xx.xxh64(data).intdigest()

else:
    _COMPILED = False

    def digest(data):
        # stdlib sha256 (C) is the safe bulk-hash fallback; the pure xxh64 is
        # only suitable for short strings (data.i path lookups).
        if isinstance(data, str):
            data = data.encode("utf-8")
        return int.from_bytes(hashlib.sha256(data).digest()[:8], "little")