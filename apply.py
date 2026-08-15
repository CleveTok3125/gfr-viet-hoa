#!/usr/bin/env python3
"""Apply the Vietnamese patch to a local GBF Relink install.

Usage:
    python3 apply.py [--game <path>] [--backup-dir <dir>]
                     [--no-ui] [--skip-backup] [--no-fix-sizes]
                     [--force] [--restore]

Steps performed, in order:
  1. locate the game (auto-detect or --game)
  2. backup data.i and the ko/ text tables
  3. patch text tables from translations.json (row-id keyed)
  4. redirect ui/.../kor/... entries to eng in data.i
  5. rewrite declared ExternalFileSizes for every patched file
  6. verify every patched table still unpacks and report stats

Idempotent: re-running on an already-patched install reports 0 patched rows.

Re-apply protection: if the install looks already patched (data.i differs
from the backup) apply.py aborts and asks for --force. Use --restore to
return the game to its pristine state from the auto-created backup.
"""
import argparse
import hashlib
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from common import bootstrap

bootstrap()
from common import (
    check_version,
    find_game_dir,
    load_filelist,
    load_translations,
)
from game_version import game_version
from patch_engine import PatchEngine
from patcher import patch_install, report
from verify import verify


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def restore(game, index, backup_dir):
    """Return the game to its pristine state using the apply-time backup.

    Restores data.i from backup_dir/data.i, then removes every loose file the
    patch creates (materialized ko/ tables, tuned *_tag.msg tables, and the
    installed fonts). Sound/ui and every archive-only file are left untouched.
    """
    backup_index = os.path.join(backup_dir, "data.i")
    if not os.path.isfile(backup_index):
        print(f"No backup found in {backup_dir} - nothing to restore.")
        sys.exit(1)

    shutil.copy2(backup_index, index)
    removed = []
    for rel in ("system/table", "font"):
        target = os.path.join(game, "data", rel)
        if os.path.isdir(target):
            shutil.rmtree(target)
            removed.append(rel)
    print("Restored data.i from " + backup_index)
    if removed:
        print("Removed loose patch files: " + ", ".join(removed))
    print("Game restored to its pristine state. Run apply.py to re-patch.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", help="path to the GBF Relink install dir")
    ap.add_argument("--backup-dir", help="where to keep pre-patch backups")
    ap.add_argument("--no-ui", action="store_true", help="skip ui kor->eng redirect")
    ap.add_argument("--skip-backup", action="store_true")
    ap.add_argument("--no-fix-sizes", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="apply anyway even if the install looks already patched")
    ap.add_argument("--restore", action="store_true",
                    help="restore the game to its pristine state from the "
                         "backup made by a previous apply run")
    args = ap.parse_args()

    game = args.game or find_game_dir()
    if not game or not os.path.isfile(os.path.join(game, "data.i")):
        print("Could not locate the game. Pass --game <path> or set GBFR_GAME.")
        sys.exit(1)
    index = os.path.join(game, "data.i")
    print(f"Game: {game}")

    backup_dir = args.backup_dir or os.path.join(game, "vietnam_backup")
    backup_index = os.path.join(backup_dir, "data.i")

    if args.restore:
        restore(game, index, backup_dir)
        sys.exit(0)

    if not args.skip_backup and os.path.isfile(backup_index):
        cur_md5 = md5_file(index)
        bak_md5 = md5_file(backup_index)
        if cur_md5 != bak_md5 and not args.force:
            print("This install looks already patched: data.i differs from the "
                  "backup in " + backup_dir)
            print("  - pass --force to re-apply anyway (idempotent), or")
            print("  - pass --restore to return the game to its pristine state.")
            sys.exit(2)

    trans = load_translations()["translations"]
    engine = PatchEngine(trans)

    meta = load_translations()["meta"]
    ver = game_version(os.path.join(game, "granblue_fantasy_relink.exe"))
    expected = meta.get("build")
    if ver:
        if expected and ver != expected:
            print(f"Game version: {ver} (patch built for {expected} - version mismatch)")
        else:
            print(f"Game version: {ver} (patch built for {expected or 'unknown'})")
    elif expected:
        print(f"Game version: unknown (patch built for {expected})")

    ok, mismatches, checked = check_version(game)
    if ok:
        print(f"Build check: OK (fingerprint match on {checked} source table(s))")
    else:
        print(f"Build check: WARNING - this install does not match the "
              f"translation build ({len(mismatches)} fingerprint mismatch(es)).")
        for path, exp, got in mismatches:
            print(f"    {path}: expected {exp[:12]}... got {got[:12]}...")
        print("    Translations may be missing new strings. Run "
              "scripts/updater.py against this build to refresh.")

    filelist = load_filelist()
    overrides = {}
    overrides_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "tag_overrides.json")
    if os.path.isfile(overrides_path):
        import json as _json
        with open(overrides_path, "r", encoding="utf-8") as fh:
            overrides = _json.load(fh)
    results = patch_install(
        game, index, engine, filelist,
        backup_dir=args.backup_dir,
        skip_backup=args.skip_backup,
        do_ui=not args.no_ui,
        do_fix_sizes=not args.no_fix_sizes,
        overrides=overrides,
    )
    report(results)

    if results["corrupt_tables"] == 0:
        mismatches = verify(game)
        if mismatches is None:
            print("Note: no release manifest - run `verify.py --gen` once to "
                  "generate data/release_manifest.json for hash verification.")
        elif mismatches:
            print(f"HASH VERIFY FAILED: {len(mismatches)} file(s) differ from the "
                  "reference manifest:")
            for rel, exp, got in mismatches:
                print(f"    {rel}: expected {exp[:12]}... got {got[:12]}...")
            print("    A previous patch may have failed - restore backups and re-apply.")
        else:
            print("Hash verify: OK (all files match the reference manifest).")

    if results["patched"] == 0 and results["corrupt_tables"] == 0:
        print("Nothing to patch - install already up to date.")
    elif results["corrupt_tables"] == 0:
        print("Done. Launch the game with language = Korean (ko).")


if __name__ == "__main__":
    main()
