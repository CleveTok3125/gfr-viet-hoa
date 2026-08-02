"""Core patch logic shared by apply.py (end-user) and build_patch.py (release)."""
import os
import shutil

import datai
from common import table_rel
from patch_engine import PatchEngine, read_msg


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

    for file in engine.iter_files():
        path = os.path.join(game, table_rel(file), file)
        if not os.path.isfile(path):
            results["missing_files"].append(file)
            continue
        r = engine.patch_file(file, path)
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
