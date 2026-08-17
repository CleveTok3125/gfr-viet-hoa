"""LZ4 block decompression with a compiled-first backend.

Prefers pip ``lz4`` (compiled) when importable, otherwise falls back to the
project's pure-Python ``vendor/lz4_block_pure``. The game stores raw LZ4
blocks (the decompressed size travels in the chunk metadata), so the block
is decompressed with the size passed separately.
"""
try:
    from lz4.block import decompress as _decompress
    _COMPILED = True
except ImportError:
    from lz4_block_pure import decompress as _decompress
    _COMPILED = False

decompress = _decompress