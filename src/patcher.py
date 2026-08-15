"""Core patch logic shared by apply.py and gfrpatch (end-user installs).

Rows are matched to their English reference by row index / id_hash, not by
the on-disk display string. This is the correct update path: after a
translation edit (or a game update) the ko/ tables may already hold
Vietnamese (or a different language) text, so matching the English key
against the current string cannot work.
"""
import os
import shutil
from typing import cast

import msgpack

import datai
from common import table_rel
from extract import extract
from patch_engine import final_text, read_msg


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
        if not (p.startswith(("system/table/text/ko/", "system/table/scenario/ko/"))):
            continue
        if extract(game, p, index_bytes) is not None:
            rels.append(p)
    return rels


FONTS_ZIP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "fonts.zip")

# The repository ships the font under its OFL name only
# (data/fonts.zip -> font/barlow-medium.msg + font/barlow-medium_1.wtb).
# The game engine hardcodes its stock font paths below, so the installer
# writes the built font under those engine paths (they exist on the game
# disk only, never in the repository) and registers each hash in data.i,
# letting the game load the loose font instead of the archive one.
ENGINE_FONT_PATHS = (
    "font/tt_pfdintextpro-regular.msg",
    "font/tt_pfdintextpro-medium.msg",
    "font/fttk_yoongothic750.msg",
)


def install_fonts(game, quiet=False):
    """Install the Vietnamese font (built from the OFL source) as loose files.

    data/fonts.zip carries a single built font under its OFL source name
    (`barlow-medium`); because the engine resolves fonts by the hardcoded
    stock paths in ENGINE_FONT_PATHS, each slot receives a copy of that font
    under the matching engine path (with its `pages.file` rewritten so the
    atlas resolves), registered in data.i's ExternalFileHashes/
    ExternalFileSizes. Idempotent; the engine-name files are install-time
    only and never appear in this repository.
    """
    if not os.path.isfile(FONTS_ZIP):
        if not quiet:
            print(f"  fonts: {FONTS_ZIP} missing - skipped")
        return 0
    import zipfile
    with zipfile.ZipFile(FONTS_ZIP) as zf:
        msg_name = next((n for n in zf.namelist() if n.endswith(".msg")), None)
        wtb_name = next((n for n in zf.namelist() if n.endswith(".wtb")), None)
        if not msg_name or not wtb_name:
            if not quiet:
                print("  fonts: fonts.zip has no .msg/.wtb entries - skipped")
            return 0
        msg_data = zf.read(msg_name)
        wtb_data = zf.read(wtb_name)

    extra_external = []
    installed = 0
    for rel in ENGINE_FONT_PATHS:
        base = os.path.basename(rel)[: -len(".msg")]
        dest = os.path.join(game, "data", rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        obj = msgpack.unpackb(msg_data, raw=False)
        obj["info"]["pages"][0]["file"] = base
        with open(dest, "wb") as out:
            out.write(cast(bytes, msgpack.packb(obj, use_bin_type=False)))
        wtb_rel = os.path.join(os.path.dirname(rel), base + "_1.wtb")
        with open(os.path.join(game, "data", wtb_rel), "wb") as out:
            out.write(wtb_data)
        extra_external.append((datai.hash_path(rel), os.path.getsize(dest)))
        extra_external.append(
            (datai.hash_path(wtb_rel),
             os.path.getsize(os.path.join(game, "data", wtb_rel))))
        installed += 1
    index = os.path.join(game, "data.i")
    added = datai.rebuild_index(index, extra_external)
    if not quiet:
        print(f"  fonts: installed {installed} font slot(s) from "
              f"{msg_name} (OFL source), {added} registered in data.i")
    return installed


def en_path(file):
    return table_rel(file).replace("/ko", "/en")[len("data/"):] + "/" + file


def patch_file_indexed(game, index, file, engine, index_bytes):
    """Apply translations to one .msg table, matching each row to its
    English reference.

    Two stages per row: (1) the Korean slot is redirected to English — the
    row shows the game's own English text when it has no Vietnamese
    translation; (2) Vietnamese is overwritten onto that EN base for every
    row the table covers. The game therefore never reads Korean text from a
    patched table. Falls back to exact-string matching if the English
    reference cannot be extracted (e.g. the reference table is absent).

    Returns the same dict shape as PatchEngine.patch_file, plus
    ``en_redirected``.
    """
    path = os.path.join(game, table_rel(file), file)
    data = read_msg(path)
    disk_rows = data["rows_"]

    raw_en = extract(game, en_path(file), index_bytes)
    if raw_en is None:
        return engine.patch_file(file, path)

    en_obj = msgpack.unpackb(raw_en, raw=False)
    en_rows = en_obj["rows_"]
    en_rows = [
        (r.get("column_", {}).get("id_hash_", ""),
         r.get("column_", {}).get("subid_hash_", ""),
         r.get("column_", {}).get("text_", ""))
        for r in en_rows
        if isinstance(r.get("column_", {}).get("text_"), str)
    ]

    id_map = None
    if len(disk_rows) != len(en_rows):
        id_map = {}
        for i, (rid, sub, _t) in enumerate(en_rows):
            id_map.setdefault((rid, sub), i)

    stat_rule = engine._stat_rule(file, en_rows)

    patched = already = en_redirected = 0
    unmatched = []
    for idx, row in enumerate(disk_rows):
        c = row.get("column_", {})
        if id_map is not None:
            key = (c.get("id_hash_", ""), c.get("subid_hash_", ""))
            src = id_map.get(key)
            if src is None:
                continue
        else:
            src = idx
        _rid, _sub, en_txt = en_rows[src]

        vn = engine.transform(file, c.get("id_hash_", ""),
                              c.get("subid_hash_", ""), en_txt, stat_rule)
        new = final_text(vn, en_txt)

        if new is None:
            unmatched.append(en_txt)
        elif new == c.get("text_", ""):
            already += 1
        elif vn:
            c["text_"] = new
            patched += 1
        else:
            c["text_"] = new
            en_redirected += 1

    if patched or en_redirected:
        from patch_engine import write_msg
        write_msg(path, data)

    return {
        "file": file,
        "path": path,
        "patched": patched,
        "already": already,
        "unmatched": unmatched,
        "en_redirected": en_redirected,
    }


def patch_install(game, index, engine, filelist,
                  backup_dir=None, skip_backup=False, do_ui=True,
                  do_fix_sizes=True, quiet=False, overrides=None):
    """Apply the Vietnamese patch to an install.

    The Korean slot is redirected to English first (UI assets via data.i,
    text tables row-by-row), then Vietnamese translations are overwritten on
    top; untranslated rows stay English, never Korean.

    Returns a results dict with keys:
      patched, already, en_redirected, unmatched, missing_files,
      ui_redirected, ui_missing, size_fixes, ok_tables, corrupt_tables.
    """
    results = {
        "patched": 0, "already": 0, "en_redirected": 0, "unmatched": 0,
        "missing_files": [],
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

    # Stage 1 (redirect first): point the Korean slot at English content,
    # for both UI assets (data.i) and every text table below. The game then
    # shows English everywhere; Vietnamese is overwritten in Stage 2.
    if do_ui:
        changed, missing = datai.patch_ui_lang(index, filelist)
        results["ui_redirected"] = changed
        results["ui_missing"] = missing
        log(f"  ui kor->eng redirected: {changed}, missing (skipped): {len(missing)}")

    for file in engine.iter_files():
        path = os.path.join(game, table_rel(file), file)
        if not os.path.isfile(path):
            results["missing_files"].append(file)
            continue
        r = patch_file_indexed(game, index, file, engine, index_bytes)
        results["patched"] += r["patched"]
        results["already"] += r["already"]
        results["en_redirected"] += r.get("en_redirected", 0)
        results["unmatched"] += len(r["unmatched"])
        if r["unmatched"]:
            log(f"  {file}: {r['patched']} patched, {r['already']} already, "
                f"{r.get('en_redirected', 0)} redirected to EN, "
                f"{len(r['unmatched'])} no reference (e.g. {r['unmatched'][0]!r})")
        else:
            log(f"  {file}: {r['patched']} patched, {r['already']} already, "
                f"{r.get('en_redirected', 0)} redirected to EN")

    install_fonts(game, quiet=quiet)

    # Recreate the tuned *_tag.msg tables from tag_tuning.json (single source
    # of truth) so an install never depends on leftover on-disk tag state.
    import tag_tuning
    tag_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tag_tuning.json")
    if os.path.isfile(tag_path):
        try:
            tag_data = tag_tuning.load(tag_path)
            tag_changed, tag_stamped = tag_tuning.write_to_game(
                game, tag_data, index, overrides=overrides)
            if tag_changed:
                log(f"  tags: wrote {len(tag_changed)} tuned tag table(s)")
            if tag_stamped:
                log(f"  tags: applied {tag_stamped} manual override range(s)")
        except Exception as e:  # noqa: BLE001 - tag tuning is best-effort
            log(f"  tags: tag_tuning.json skipped ({e})")
    else:
        log("  tags: tag_tuning.json missing - tag tables left as-is")

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
        except Exception as e:  # noqa: BLE001 - one corrupt table must not abort the patch
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
    log(f"  rows en redirected: {results.get('en_redirected', 0)}")
    log(f"  rows no reference: {results['unmatched']}")
    log(f"  missing files    : {len(results['missing_files'])}")
    log(f"  ui redirected    : {results['ui_redirected']}")
    log(f"  sizes fixed      : {len(results['size_fixes'])}")
    log(f"  verify           : {results['ok_tables']} tables OK, "
        f"{results['corrupt_tables']} corrupt")
