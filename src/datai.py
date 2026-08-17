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

from deps.xxh64 import xxh64
from gbfr_schema import IndexFile


def hash_path(p):
    return xxh64(p)


def _vec_data(buf, root, field_vt):
    fa = root._tab.Pos + root._tab.Offset(field_vt)
    uf = encode.Get(number_types.UOffsetTFlags.packer_type, buf, fa)
    return fa + uf + 4


def load_root(path):
    with open(path, "rb") as fh:
        buf = bytearray(fh.read())
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
        with open(index_path, "wb") as fh:
            fh.write(bytes(buf))
    return fixes


def read_external(index_path):
    """Return the external-file vectors as (hashes, sizes), sorted by hash.

    The game keeps ExternalFileHashes sorted (binary searched); the two
    vectors are parallel, so hashes[i] maps to sizes[i].
    """
    buf, root = load_root(index_path)
    vh = _vec_data(buf, root, 16)
    vs = _vec_data(buf, root, 18)
    n = root.ExternalFileHashesLength()
    items = []
    for i in range(n):
        h = struct.unpack("<Q", buf[vh + i * 8:vh + i * 8 + 8])[0]
        s = struct.unpack("<Q", buf[vs + i * 8:vs + i * 8 + 8])[0]
        items.append((h, s))
    items.sort()
    return items


def rebuild_index(index_path, extra_external=None):
    """Rewrite data.i, merging `extra_external` (list of (hash, size)) into
    the ExternalFileHashes/ExternalFileSizes vectors.

    Every other field is preserved byte-for-byte, so the rebuilt index is
    identical to the original except for the merged external entries. This is
    required because FlatBuffers vectors cannot be resized in place.
    """
    import flatbuffers

    from gbfr_schema import IndexFile as IF

    buf, root = load_root(index_path)
    src = bytes(buf)

    def rb(slot, esz):
        o = root._tab.Offset(slot)
        if o == 0:
            return b"", 0
        va = root._tab.Vector(o)
        n = root._tab.VectorLen(o)
        return src[va:va + n * esz], n

    def rstr(slot):
        o = root._tab.Offset(slot)
        return root._tab.String(o + root._tab.Pos) if o else None

    codename = rstr(4)
    num = root.NumArchives()
    seed = root.XxhashSeed()
    archive, _ = rb(10, 8)
    f2c, nf2c = rb(12, 12)
    chunks, nch = rb(14, 24)
    _exthash, _ = rb(16, 8)
    _extsize, _ = rb(18, 8)
    cached, _ = rb(20, 4)

    # resolve existing parallel external vectors
    cur = read_external(index_path)
    by_hash = {h: s for h, s in cur}
    for h, s in (extra_external or []):
        if h not in by_hash or by_hash[h] != s:
            by_hash[h] = s
    merged = sorted(by_hash.items())

    b = flatbuffers.Builder(0)
    codename_off = b.CreateString(codename.decode()) if codename else 0
    arch_v = IF.CreateArchiveFileHashesVector(
        b, [struct.unpack("<Q", archive[i:i + 8])[0] for i in range(0, len(archive), 8)])
    IF.StartFileToChunkIndexersVector(b, nf2c)
    for i in range(nf2c - 1, -1, -1):
        r = f2c[i * 12:i * 12 + 12]
        b.Prep(4, 12)
        for j in range(11, -1, -1):
            b.PrependUint8(r[j])
    f2c_v = b.EndVector()
    IF.StartChunksVector(b, nch)
    for i in range(nch - 1, -1, -1):
        cv = chunks[i * 24:i * 24 + 24]
        b.Prep(8, 24)
        for j in range(23, -1, -1):
            b.PrependUint8(cv[j])
    chunks_v = b.EndVector()
    eh_v = IF.CreateExternalFileHashesVector(b, [h for h, _ in merged])
    es_v = IF.CreateExternalFileSizesVector(b, [s for _, s in merged])
    cache_v = IF.CreateCachedChunkIndicesVector(
        b, [struct.unpack("<I", cached[i:i + 4])[0] for i in range(0, len(cached), 4)])
    IF.Start(b)
    IF.AddCodename(b, codename_off)
    IF.AddNumArchives(b, num)
    IF.AddXxhashSeed(b, seed)
    IF.AddArchiveFileHashes(b, arch_v)
    IF.AddFileToChunkIndexers(b, f2c_v)
    IF.AddChunks(b, chunks_v)
    IF.AddExternalFileHashes(b, eh_v)
    IF.AddExternalFileSizes(b, es_v)
    IF.AddCachedChunkIndices(b, cache_v)
    end = IF.End(b)
    b.Finish(end)
    with open(index_path, "wb") as f:
        f.write(bytes(b.Output()))
    return len(merged) - len(cur)  # number of entries added/updated


def materialize_loose(game_dir, index_path, rel_paths):
    """Extract `rel_paths` (e.g. system/table/text/ko/...) from the archive
    into loose files under `game_dir/data`, and register each in data.i's
    ExternalFileHashes/ExternalFileSizes.

    Purely idempotent: files already present on disk and already registered
    are left untouched. Returns (created, registered).
    """
    if not rel_paths:
        return 0, 0
    from extract import extract
    with open(index_path, "rb") as fh:
        index_bytes = fh.read()
    created = 0
    extra = []
    for rel in rel_paths:
        disk = os.path.join(game_dir, "data", rel)
        if not os.path.isfile(disk):
            raw = extract(game_dir, rel, index_bytes)
            if raw is None:
                continue  # not present in archive for this build
            os.makedirs(os.path.dirname(disk), exist_ok=True)
            with open(disk, "wb") as f:
                f.write(raw)
            created += 1
        else:
            with open(disk, "rb") as fh:
                raw = fh.read()
        extra.append((hash_path(rel), os.path.getsize(disk) if os.path.isfile(disk) else len(raw)))
    registered = 0
    if extra:
        registered = rebuild_index(index_path, extra)
    return created, registered


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
        with open(index_path, "wb") as fh:
            fh.write(bytes(buf))
    return changed, missing
