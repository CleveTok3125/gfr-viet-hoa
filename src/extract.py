"""Extract a file from a GBF Relink data.i archive by internal path."""
import os
import struct

from deps.lz4_block import decompress as _lz4_decompress
from deps.xxh64 import xxh64
from gbfr_schema import IndexFile


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


def _locate(game_dir, path, index_bytes=None):
    """Resolve `path` to its archive chunk; return (dfn, foff, zsize, usize,
    off, fsz) or None when the path is not in the archive."""
    if index_bytes is None:
        index_path = os.path.join(game_dir, "data.i")
        with open(index_path, "rb") as fh:
            index_bytes = fh.read()
    root = IndexFile.IndexFile.GetRootAs(index_bytes, 0)

    target = xxh64(path)
    idx = find_archive_index(root, target)
    if idx is None:
        return None

    vfileidx = vec_data(index_bytes, root, 12)   # FileToChunkIndexers, stride 12
    vchunk = vec_data(index_bytes, root, 14)     # Chunks, stride 24

    ci = struct.unpack('<i', index_bytes[vfileidx + idx * 12: vfileidx + idx * 12 + 4])[0]
    fsz = struct.unpack('<I', index_bytes[vfileidx + idx * 12 + 4: vfileidx + idx * 12 + 8])[0]
    off = struct.unpack('<I', index_bytes[vfileidx + idx * 12 + 8: vfileidx + idx * 12 + 12])[0]
    foff = struct.unpack('<Q', index_bytes[vchunk + ci * 24: vchunk + ci * 24 + 8])[0]
    zsize = struct.unpack('<I', index_bytes[vchunk + ci * 24 + 8: vchunk + ci * 24 + 12])[0]
    usize = struct.unpack('<I', index_bytes[vchunk + ci * 24 + 12: vchunk + ci * 24 + 16])[0]
    dfn = index_bytes[vchunk + ci * 24 + 22]
    return dfn, foff, zsize, usize, off, fsz


def extract(game_dir, path, index_bytes=None):
    """Return file bytes for `path` (internal, no 'data/' prefix), or None.

    Pass `index_bytes` (the raw bytes of data.i) to avoid re-reading the
    index file on every call.
    """
    loc = _locate(game_dir, path, index_bytes)
    if loc is None:
        return None
    dfn, foff, zsize, usize, off, fsz = loc
    with open(os.path.join(game_dir, f"data.{dfn}"), "rb") as f:
        f.seek(foff)
        raw = f.read(zsize)
    data = _lz4_decompress(raw, usize) if zsize != usize else raw
    return data[off:off + fsz]


def chunk_digest(game_dir, path, index_bytes=None):
    """xxh64 of the compressed archive chunk containing `path`, or None.

    The digest is computed over the raw (still-compressed) chunk bytes, so
    verifying a cached extraction result costs a file read plus one xxh64
    (compiled: GB/s) instead of an LZ4 decompress + msgpack decode. Any file
    sharing the chunk invalidates together with `path`; that only makes the
    cache conservatively miss, never return stale data.
    """
    from deps.xxh64 import digest as _digest

    loc = _locate(game_dir, path, index_bytes)
    if loc is None:
        return None
    dfn, foff, zsize, _, _, _ = loc
    with open(os.path.join(game_dir, f"data.{dfn}"), "rb") as f:
        f.seek(foff)
        return _digest(f.read(zsize))
