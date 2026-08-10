"""Extract a file from a GBF Relink data.i archive by internal path."""
import os
import struct

from gbfr_schema import IndexFile
from lz4_block_pure import decompress as _lz4_decompress
from xxh64_pure import xxh64


def vec_data(buf, root, field_vt):
    fa = root._tab.Pos + root._tab.Offset(field_vt)
    from flatbuffers import encode, number_types
    uf = encode.Get(number_types.UOffsetTFlags.packer_type, buf, fa)
    return fa + uf + 4


def find_archive_index(root, target):
    """Binary search ArchiveFileHashes; returns index or None."""
    n = root.ArchiveFileHashesLength()
    lo, hi = 0, n
    while lo < hi:
        mid = (lo + hi) // 2
        if root.ArchiveFileHashes(mid) < target:
            lo = mid + 1
        else:
            hi = mid
    if lo < n and root.ArchiveFileHashes(lo) == target:
        return lo
    return None


def extract(game_dir, path, index_bytes=None):
    """Return file bytes for `path` (internal, no 'data/' prefix), or None.

    Pass `index_bytes` (the raw bytes of data.i) to avoid re-reading the
    index file on every call.
    """
    if index_bytes is None:
        index_path = os.path.join(game_dir, "data.i")
        with open(index_path, "rb") as fh:
            buf = fh.read()
    else:
        buf = index_bytes
    root = IndexFile.IndexFile.GetRootAs(buf, 0)

    target = xxh64(path)
    idx = find_archive_index(root, target)
    if idx is None:
        return None

    vfileidx = vec_data(buf, root, 12)   # FileToChunkIndexers, stride 12
    vchunk = vec_data(buf, root, 14)     # Chunks, stride 24

    ci = struct.unpack('<i', buf[vfileidx + idx * 12: vfileidx + idx * 12 + 4])[0]
    fsz = struct.unpack('<I', buf[vfileidx + idx * 12 + 4: vfileidx + idx * 12 + 8])[0]
    off = struct.unpack('<I', buf[vfileidx + idx * 12 + 8: vfileidx + idx * 12 + 12])[0]
    foff = struct.unpack('<Q', buf[vchunk + ci * 24: vchunk + ci * 24 + 8])[0]
    zsize = struct.unpack('<I', buf[vchunk + ci * 24 + 8: vchunk + ci * 24 + 12])[0]
    usize = struct.unpack('<I', buf[vchunk + ci * 24 + 12: vchunk + ci * 24 + 16])[0]
    dfn = buf[vchunk + ci * 24 + 22]

    with open(os.path.join(game_dir, f"data.{dfn}"), "rb") as f:
        f.seek(foff)
        raw = f.read(zsize)
    data = _lz4_decompress(raw, usize) if zsize != usize else raw
    return data[off:off + fsz]
