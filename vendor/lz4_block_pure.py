"""Pure-Python LZ4 block decompressor (LZ4 block format v1.9).

Only the block format used by GBFR data chunks is implemented: a stream of
[token][literals][match-offset][match] sequences. This replaces the binary
`lz4` package so the repo ships no compiled artifacts.

Usage:
    from lz4_block_pure import decompress
    out = decompress(data, uncompressed_size=None)
"""


class LZ4Error(Exception):
    pass


def _read_length(data, i, start):
    """Extended length encoding: 15 + sum of following bytes."""
    length = start
    while i < len(data):
        b = data[i]
        i += 1
        length += b
        if b != 255:
            break
    return length, i


def decompress(data, uncompressed_size=None):
    """Decompress a single LZ4 block. `data` must be bytes."""
    if isinstance(data, memoryview):
        data = bytes(data)
    if not isinstance(data, (bytes, bytearray)):
        raise LZ4Error("input must be bytes")
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        token = data[i]
        i += 1
        lit_len = token >> 4
        match_len = token & 0x0F

        if lit_len == 15:
            lit_len, i = _read_length(data, i, 15)
        if i + lit_len > n:
            raise LZ4Error("literal sequence overruns block")
        out += data[i:i + lit_len]
        i += lit_len

        if i >= n:
            break

        if i + 2 > n:
            raise LZ4Error("truncated match offset")
        offset = data[i] | (data[i + 1] << 8)
        i += 2
        if offset == 0 or offset > len(out):
            raise LZ4Error("invalid match offset")

        if match_len == 15:
            match_len, i = _read_length(data, i, 15)
        match_len += 4

        if match_len <= offset:
            out += out[-offset:][:match_len]
        else:
            # overlapping match: copy byte by byte
            for _ in range(match_len):
                out.append(out[-offset])

    if uncompressed_size is not None and len(out) != uncompressed_size:
        raise LZ4Error(
            f"expected {uncompressed_size} bytes, got {len(out)}")
    return bytes(out)
