"""Core patch logic shared by apply.py (end-user) and build_patch.py (release).

Rows are matched to their English reference by row index / id_hash, not by
the on-disk display string. This is the correct update path: after a
translation edit (or a game update) the ko/ tables may already hold
Vietnamese (or a different language) text, so matching the English key
against the current string cannot work.
"""
import os
import shutil

import msgpack

import datai
from common import table_rel
from extract import extract
from patch_engine import PatchEngine, read_msg


def loose_ko_paths(game, index_bytes):
    """Return the ko/ text + scenario .msg paths to materialize as loose files.

    We reuse the bundled filelist to enumerate candidate `system/table/
    {text,scenario}/ko/*.msg` paths and keep the ones that actually exist in
    this build's archive. This is what turns an archive-only install (the
    pristine game) into one whose ko/ tables live on disk, where patching
    happens.
    """
    from common import load_filelist
    rels = []
    for p in load_filelist():
        if not p.endswith(".msg"):
            continue
        if not (p.startswith("system/table/text/ko/") or
                p.startswith("system/table/scenario/ko/")):
            continue
        if extract(game, p, index_bytes) is not None:
            rels.append(p)
    return rels


FONTS_ZIP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "fonts.zip")


def install_fonts(game, quiet=False):
    """Install the bundled Vietnamese fonts (data/fonts.zip) as loose files.

    The fonts carry the glyphs needed to render Vietnamese (the stock
    yoongothic font in the archives does not). They are written to
    data/font/ and each hash is registered in data.i's ExternalFileHashes/
    ExternalFileSizes so the game loads the loose file instead of the archive
    one (same mechanism as the ko/ tables). Idempotent.
    """
    if not os.path.isfile(FONTS_ZIP):
        if not quiet:
            print(f"  fonts: {FONTS_ZIP} missing - skipped")
        return 0
    import zipfile
    index = os.path.join(game, "data.i")
    extra_external = []
    installed = 0
    with zipfile.ZipFile(FONTS_ZIP) as zf:
        for name in zf.namelist():
            dest = os.path.join(game, "data", name)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(name) as src, open(dest, "wb") as out:
                out.write(src.read())
            extra_external.append((datai.hash_path(name), os.path.getsize(dest)))
            installed += 1
    added = datai.rebuild_index(index, extra_external)
    if not quiet:
        print(f"  fonts: installed {installed} font file(s), "
              f"{added} registered in data.i")
    return installed


def en_path(file):
    return table_rel(file).replace("/ko", "/en")[len("data/"):] + "/" + file


def patch_file_indexed(game, index, file, engine, index_bytes):
    """Apply translations to one .msg table, matching each row to its
    English reference. Returns the same dict shape as PatchEngine.patch_file.

    Falls back to exact-string matching if the English reference cannot be
    extracted (e.g. the reference table is absent).
    """
    path = os.path.join(game, table_rel(file), file)
    data = read_msg(path)
    disk_rows = data["rows_"]

    raw_en = extract(game, en_path(file), index_bytes)
    if raw_en is None:
        return engine.patch_file(file, path)

    en_obj = msgpack.unpackb(raw_en, raw=False)
    en_rows = en_obj["rows_"]

    id_map = None
    if len(disk_rows) != len(en_rows):
        id_map = {}
        for i, r in enumerate(en_rows):
            c = r["column_"]
            key = (c.get("id_hash_", ""), c.get("subid_hash_", ""))
            id_map.setdefault(key, i)

    tbl = engine.translations.get(file)
    do_node = (engine._node_re is not None and
               file in (engine.rules.get("skillboard_node_transform") or {}).get("files", []))

    patched = already = 0
    unmatched = []
    for idx, row in enumerate(disk_rows):
        if id_map is not None:
            c = row["column_"]
            key = (c.get("id_hash_", ""), c.get("subid_hash_", ""))
            src = id_map.get(key)
            if src is None:
                continue
        else:
            src = idx
        en_txt = en_rows[src]["column_"]["text_"]

        new = None
        if tbl and en_txt in tbl:
            new = tbl[en_txt]
        elif do_node:
            m = engine._node_re.match(en_txt)
            if m:
                new = f"{m.group(1)}:\n{engine.stat_map[m.group(2)]}"

        if new is None:
            unmatched.append(en_txt)
        elif new == row["column_"]["text_"]:
            already += 1
        else:
            row["column_"]["text_"] = new
            patched += 1

    if patched:
        from patch_engine import write_msg
        write_msg(path, data)

    return {
        "file": file,
        "path": path,
        "patched": patched,
        "already": already,
        "unmatched": unmatched,
    }


def patch_install(game, index, engine, filelist,
                  backup_dir=None, skip_backup=False, do_ui=True,
                  do_fix_sizes=True, quiet=False):
    """Apply the Vietnamese patch to an install.

    Returns a results dict with keys:
      patched, already, unmatched, missing_files, ui_redirected,
      ui_missing, size_fixes, ok_tables, corrupt_tables.
    """
    results = {
        "patched": 0, "already": 0, "unmatched": 0, "missing_files": [],
        "ui_redirected": 0, "ui_missing": [], "size_fixes": [],
        "ok_tables": 0, "corrupt_tables": 0,
    }

    def log(msg):
        if not quiet:
            print(msg)

    if not skip_backup:
        backup_dir = backup_dir or os.path.join(game, "vietnam_backup")
        datai.backup(index, backup_dir)
        for rel in sorted({table_rel(f) for f in engine.iter_files()}):
            src_dir = os.path.join(game, rel)
            if os.path.isdir(src_dir):
                shutil.copytree(src_dir, os.path.join(backup_dir, os.path.basename(rel)),
                                dirs_exist_ok=True)
        log(f"Backup -> {backup_dir}")

    with open(index, "rb") as f:
        index_bytes = f.read()

    # Materialize archive-only ko/ tables into loose files so patching can
    # modify them, and register them in data.i (idempotent for loose installs).
    loose = loose_ko_paths(game, index_bytes)
    created, registered = datai.materialize_loose(game, index, loose)
    if created or registered:
        log(f"  materialized ko tables: {created} file(s), "
            f"{registered} registered in data.i")
        with open(index, "rb") as f:
            index_bytes = f.read()

    for file in engine.iter_files():
        path = os.path.join(game, table_rel(file), file)
        if not os.path.isfile(path):
            results["missing_files"].append(file)
            continue
        r = patch_file_indexed(game, index, file, engine, index_bytes)
        results["patched"] += r["patched"]
        results["already"] += r["already"]
        results["unmatched"] += len(r["unmatched"])
        if r["unmatched"]:
            log(f"  {file}: {r['patched']} patched, {r['already']} already, "
                f"{len(r['unmatched'])} unmatched (e.g. {r['unmatched'][0]!r})")
        else:
            log(f"  {file}: {r['patched']} patched, {r['already']} already")

    if do_ui:
        changed, missing = datai.patch_ui_lang(index, filelist)
        results["ui_redirected"] = changed
        results["ui_missing"] = missing
        log(f"  ui kor->eng redirected: {changed}, missing (skipped): {len(missing)}")

    install_fonts(game, quiet=quiet)

    if do_fix_sizes:
        fixes = datai.fix_sizes(
            game, index,
            [os.path.join(table_rel(f)[len("data/"):], f) for f in engine.iter_files()],
        )
        results["size_fixes"] = fixes
        log(f"  external sizes fixed: {len(fixes)}")

    for file in engine.iter_files():
        path = os.path.join(game, table_rel(file), file)
        if not os.path.isfile(path):
            continue
        try:
            data = read_msg(path)
            if isinstance(data, dict) and "rows_" in data:
                results["ok_tables"] += 1
            else:
                results["corrupt_tables"] += 1
        except Exception as e:
            results["corrupt_tables"] += 1
            log(f"  CORRUPT {file}: {e}")

    return results


def report(results, quiet=False):
    def log(msg):
        if not quiet:
            print(msg)

    log("Summary:")
    log(f"  rows patched     : {results['patched']}")
    log(f"  rows already     : {results['already']}")
    log(f"  rows unmatched   : {results['unmatched']}")
    log(f"  missing files    : {len(results['missing_files'])}")
    log(f"  ui redirected    : {results['ui_redirected']}")
    log(f"  sizes fixed      : {len(results['size_fixes'])}")
    log(f"  verify           : {results['ok_tables']} tables OK, "
        f"{results['corrupt_tables']} corrupt")
