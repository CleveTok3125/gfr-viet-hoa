"""Direct binary surgery on the game's data.i index file.

data.i is a FlatBuffers IndexFile. Two vectors matter here:

  * ExternalFileHashes (uint64, vtable slot 16) — xxh64 hash of each loose
    file's game-relative path.
  * ExternalFileSizes  (uint64, vtable slot 18) — declared byte size of each
    loose file. The game validates these against disk, so any patched text
    file whose size changed must have its declared size rewritten.
  * FileToChunkIndexers (12-byte structs, vtable slot 12) — maps archive file
    hashes to chunk data. Patching `ui/.../kor/...` paths to their `eng`
    counterpart is done by copying the eng 12-byte struct into the kor slot.

All hashes use xxh64 of the lowercase path (seed 0), matching the game.
"""
import bisect
import os
import shutil
import struct

from flatbuffers import encode, number_types

from gbfr_schema import IndexFile
from xxh64_pure import xxh64


def hash_path(p):
    return xxh64(p)


def _vec_data(buf, root, field_vt):
    fa = root._tab.Pos + root._tab.Offset(field_vt)
    uf = encode.Get(number_types.UOffsetTFlags.packer_type, buf, fa)
    return fa + uf + 4


def load_root(path):
    buf = bytearray(open(path, "rb").read())
    root = IndexFile.IndexFile.GetRootAs(bytes(buf), 0)
    return buf, root


def backup(path, backup_dir):
    os.makedirs(backup_dir, exist_ok=True)
    dest = os.path.join(backup_dir, os.path.basename(path))
    if not os.path.exists(dest):
        shutil.copy2(path, dest)
    return dest


def fix_sizes(game_dir, index_path, paths_to_fix):
    """Rewrite declared ExternalFileSizes for the given game-relative loose
    paths so they match the actual on-disk size. Returns a list of fixes."""
    buf, root = load_root(index_path)
    vhash = _vec_data(buf, root, 16)
    vsize = _vec_data(buf, root, 18)
    n = root.ExternalFileHashesLength()
    fixes = []
    for rel in paths_to_fix:
        h = hash_path(rel)
        disk = os.path.join(game_dir, "data", rel)
        if not os.path.exists(disk):
            continue
        actual = os.path.getsize(disk)
        lo, hi = 0, n
        while lo < hi:
            mid = (lo + hi) // 2
            if struct.unpack("<Q", buf[vhash + mid * 8:vhash + mid * 8 + 8])[0] < h:
                lo = mid + 1
            else:
                hi = mid
        if lo >= n or struct.unpack("<Q", buf[vhash + lo * 8:vhash + lo * 8 + 8])[0] != h:
            continue
        declared = struct.unpack("<Q", buf[vsize + lo * 8:vsize + lo * 8 + 8])[0]
        if declared != actual:
            struct.pack_into("<Q", buf, vsize + lo * 8, actual)
            fixes.append((rel, declared, actual))
    if fixes:
        open(index_path, "wb").write(bytes(buf))
    return fixes


def patch_ui_lang(index_path, filelist):
    """Redirect every `ui/.../kor/...` entry to its `eng` counterpart by
    copying the 12-byte FileToChunkIndexer struct. Returns (changed, missing)."""
    buf, root = load_root(index_path)
    n = root.ArchiveFileHashesLength()
    arch = [root.ArchiveFileHashes(i) for i in range(n)]
    vtable_field = root._tab.Offset(12)
    field_abs = root._tab.Pos + vtable_field
    uf = encode.Get(number_types.UOffsetTFlags.packer_type, buf, field_abs)
    vec_data = field_abs + uf + 4

    kor_paths = [p for p in filelist if p and p.startswith("ui/") and "/kor/" in p]

    missing = []
    changed = 0
    for p in kor_paths:
        ep = p.replace("/kor/", "/eng/")
        eh = hash_path(ep)
        kh = hash_path(p)
        i = bisect.bisect_left(arch, eh)
        if i >= n or arch[i] != eh:
            missing.append(ep)
            continue
        j = bisect.bisect_left(arch, kh)
        if j >= n or arch[j] != kh:
            missing.append(p)
            continue
        if j == i:
            continue
        es, ks = vec_data + i * 12, vec_data + j * 12
        if buf[ks:ks + 12] != buf[es:es + 12]:
            buf[ks:ks + 12] = buf[es:es + 12]
            changed += 1
    if changed:
        open(index_path, "wb").write(bytes(buf))
    return changed, missing
