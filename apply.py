#!/usr/bin/env python3
"""Apply the Vietnamese patch to a local GBF Relink install.

Usage:
    python3 apply.py [--game <path>] [--backup-dir <dir>]
                     [--no-ui] [--skip-backup] [--no-fix-sizes]

Steps performed, in order:
  1. locate the game (auto-detect or --game)
  2. backup data.i and the ko/ text tables
  3. patch text tables from translations.json (+ rules.json node transforms)
  4. redirect ui/.../kor/... entries to eng in data.i
  5. rewrite declared ExternalFileSizes for every patched file
  6. verify every patched table still unpacks and report stats

Idempotent: re-running on an already-patched install reports 0 patched rows.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from common import bootstrap
bootstrap()
from common import load_translations, load_rules, load_filelist, find_game_dir, check_version
from game_version import game_version
from patch_engine import PatchEngine
from patcher import patch_install, report
from verify import verify


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", help="path to the GBF Relink install dir")
    ap.add_argument("--backup-dir", help="where to keep pre-patch backups")
    ap.add_argument("--no-ui", action="store_true", help="skip ui kor->eng redirect")
    ap.add_argument("--skip-backup", action="store_true")
    ap.add_argument("--no-fix-sizes", action="store_true")
    args = ap.parse_args()

    trans = load_translations()["translations"]
    rules = load_rules()
    engine = PatchEngine(trans, rules)

    game = args.game or find_game_dir()
    if not game or not os.path.isfile(os.path.join(game, "data.i")):
        print("Could not locate the game. Pass --game <path> or set GBFR_GAME.")
        sys.exit(1)
    index = os.path.join(game, "data.i")
    print(f"Game: {game}")

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
        print("    Translations may be missing new strings. Run updater.py "
              "against this build to refresh.")

    filelist = load_filelist()
    results = patch_install(
        game, index, engine, filelist,
        backup_dir=args.backup_dir,
        skip_backup=args.skip_backup,
        do_ui=not args.no_ui,
        do_fix_sizes=not args.no_fix_sizes,
    )
    report(results)

    if results["corrupt_tables"] == 0:
        mismatches = verify(game)
        if mismatches is None:
            print("Note: no release manifest - run build_patch.py once to generate "
                  "data/release_manifest.json for hash verification.")
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
