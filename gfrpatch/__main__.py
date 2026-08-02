#!/usr/bin/env python3
"""Entry point: python3 -m gfrpatch

Patches a GBF Relink install with the Vietnamese tables. If no --game is
given, the path is asked interactively (the tool also prints any
auto-detected candidates as a hint), so no directory guessing is needed.
"""
import argparse
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO, os.path.join(REPO, "src"), os.path.join(REPO, "vendor")):
    if p not in sys.path:
        sys.path.insert(0, p)

from common import bootstrap
bootstrap()
from common import load_translations, load_rules, load_filelist, find_game_dir, check_version
from game_version import game_version
from patch_engine import PatchEngine
from patcher import patch_install, report
from verify import verify


def pick_game_dir(explicit):
    if explicit:
        return explicit
    found = find_game_dir()
    if found:
        print(f"Detected an install at: {found}")
    print("Type the full path to your Granblue Fantasy - Relink folder")
    print("(the one containing data.i). Paths with spaces are fine.")
    while True:
        try:
            answer = input("Game folder> ").strip().strip('"').strip()
        except EOFError:
            return None
        if not answer:
            print("Empty path. Ctrl-C to quit, or type the path.")
            continue
        if os.path.isfile(os.path.join(answer, "data.i")):
            return answer
        print(f"No data.i found under {answer!r}; try again.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", help="path to the game install (asked if omitted)")
    ap.add_argument("--backup-dir", help="where to keep pre-patch backups")
    ap.add_argument("--no-ui", action="store_true")
    ap.add_argument("--skip-backup", action="store_true")
    ap.add_argument("--no-fix-sizes", action="store_true")
    args = ap.parse_args()

    game = pick_game_dir(args.game)
    if not game:
        print("No game path provided; aborting.")
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
        print(f"Build check: WARNING - this install does not match the translation "
              f"build ({len(mismatches)} fingerprint mismatch(es)); run updater.py "
              "to refresh.")

    trans = load_translations()["translations"]
    rules = load_rules()
    engine = PatchEngine(trans, rules)
    filelist = load_filelist()
    results = patch_install(game, index, engine, filelist,
                            backup_dir=args.backup_dir,
                            skip_backup=args.skip_backup,
                            do_ui=not args.no_ui,
                            do_fix_sizes=not args.no_fix_sizes)
    report(results)

    if results["corrupt_tables"] == 0:
        mism = verify(game)
        if mism is None:
            print("Note: no release manifest - run build_patch.py once to generate "
                  "data/release_manifest.json for hash verification.")
        elif mism:
            print(f"HASH VERIFY FAILED: {len(mism)} file(s) differ from the "
                  "reference manifest; restore backups and re-apply.")
        else:
            print("Hash verify: OK (all files match the reference manifest).")

    if results["patched"] == 0 and results["corrupt_tables"] == 0:
        print("Nothing to patch - install already up to date.")
    elif results["corrupt_tables"] == 0:
        print("Done. Launch the game with language = Korean (ko).")


if __name__ == "__main__":
    main()
