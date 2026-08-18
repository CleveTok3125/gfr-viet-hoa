#!/usr/bin/env python3
"""Entry point: python3 -m gfrpatch

Patches a GBF Relink install with the Vietnamese tables. If no --game is
given, the path is asked interactively (the tool also prints any
auto-detected candidates as a hint), so no directory guessing is needed.
"""
import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO, os.path.join(REPO, "src"), os.path.join(REPO, "vendor")):
    if p not in sys.path:
        sys.path.insert(0, p)

from common import bootstrap

bootstrap()
from apply import md5_file, restore
from common import (
    check_version,
    find_game_dir,
    load_filelist,
    load_translations,
)
from game_version import game_version
from patch_engine import PatchEngine
from patcher import patch_install, report
from release_build import stamp_release
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


def run_edit(game, file, search, id_, range_, speaker, rebuild):
    """Launch the TUI editor (src/tr_edit.py) as a child process.

    Without ``--rebuild`` the process is replaced by the editor (``execv``);
    with it the editor runs as a child so the caller can rebuild the patch
    once it exits. Returns the editor exit code when run as a child.
    """
    src = os.path.join(REPO, "src", "tr_edit.py")
    cmd = [sys.executable, src]
    if game:
        cmd += ["--game", game]
    if file:
        cmd += ["--file", file]
    if search:
        cmd += ["--search", search]
    if id_:
        cmd += ["--id", id_]
    if range_:
        cmd += ["--range", range_]
    if speaker:
        cmd += ["--speaker", speaker]
    print("Launching editor: " + " ".join(cmd))
    if rebuild:
        return subprocess.call(cmd)
    return os.execv(sys.executable, cmd)


def apply_patch(game, backup_dir=None, skip_backup=False, no_ui=False,
                no_fix_sizes=False, force=False, rebuild=False, reapply=False):
    """Apply the Vietnamese patch to a resolved game dir and verify it.

    ``rebuild`` writes a fresh release manifest instead of hash-checking the
    old one. ``reapply`` bypasses the already-patched guard: the caller has an
    explicit reason to re-apply (e.g. ``edit --rebuild`` after saving rows).
    Returns a process exit code (0 = success).
    """
    index = os.path.join(game, "data.i")
    if not os.path.isfile(index):
        print(f"No data.i under {game!r} - cannot patch.")
        return 2
    print(f"Game: {game}")

    backup_dir = backup_dir or os.path.join(game, "vietnam_backup")
    backup_index = os.path.join(backup_dir, "data.i")

    if not skip_backup and not reapply and os.path.isfile(backup_index):
        cur_md5 = md5_file(index)
        bak_md5 = md5_file(backup_index)
        if cur_md5 != bak_md5 and not force:
            print("This install looks already patched: data.i differs from the "
                  "backup in " + backup_dir)
            print("  - pass --force to re-apply anyway (idempotent), or")
            print("  - pass --restore to return the game to its pristine state.")
            return 2

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
              f"build ({len(mismatches)} fingerprint mismatch(es)); run "
              "scripts/updater.py to refresh.")

    trans = load_translations()["translations"]
    engine = PatchEngine(trans)
    filelist = load_filelist()
    overrides = {}
    overrides_path = os.path.join(REPO, "tag_overrides.json")
    if os.path.isfile(overrides_path):
        import json as _json
        with open(overrides_path, "r", encoding="utf-8") as fh:
            overrides = _json.load(fh)
    results = patch_install(game, index, engine, filelist,
                            backup_dir=backup_dir,
                            skip_backup=skip_backup,
                            do_ui=not no_ui,
                            do_fix_sizes=not no_fix_sizes,
                            overrides=overrides)
    report(results)

    if results["corrupt_tables"] == 0:
        if rebuild:
            from verify import gen_manifest
            gen_manifest(game)
        else:
            mism = verify(game)
            if mism is None:
                print("Note: no release manifest - run `verify.py --gen` once to "
                      "generate data/release_manifest.json for hash verification.")
            elif mism:
                print(f"HASH VERIFY FAILED: {len(mism)} file(s) differ from the "
                      "reference manifest; restore backups and re-apply.")
                for rel, exp, got in mism:
                    print(f"    {rel}: expected {exp[:12]}... got {got[:12]}...")
            else:
                print("Hash verify: OK (all files match the reference manifest).")

    if results["patched"] == 0 and results["corrupt_tables"] == 0:
        print("Nothing to patch - install already up to date.")
    elif results["corrupt_tables"] == 0:
        print("Done. Launch the game with language = Korean (ko).")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", help="path to the game install (asked if omitted)")
    ap.add_argument("--backup-dir", help="where to keep pre-patch backups")
    ap.add_argument("--no-ui", action="store_true")
    ap.add_argument("--skip-backup", action="store_true")
    ap.add_argument("--no-fix-sizes", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="apply anyway even if the install looks already patched")
    ap.add_argument("--restore", action="store_true",
                    help="restore the game to its pristine state from the "
                         "backup made by a previous apply run")
    ap.add_argument("--rebuild", action="store_true",
                    help="restore to pristine, re-apply the patch, then write a "
                         "fresh release manifest (gen_manifest) instead of "
                         "hash-verifying against the old one")
    sub = ap.add_subparsers(dest="sub", metavar="subcommand")
    ep = sub.add_parser(
        "edit", help="launch the interactive TUI translation editor (tr_edit)",
        description="Launch the interactive TUI editor for text + highlight "
                    "markers (src/tr_edit.py).")
    ep.add_argument("--game", help="path to the game install (for EN/JA reference)")
    ep.add_argument("--file", default=None,
                    help="initial table basename, e.g. text_scenario_030")
    ep.add_argument("--search", default=None,
                    help="pre-fill the search box (EN / VN / ID, * ? wildcards)")
    ep.add_argument("--id", default=None,
                    help="pre-fill the ID filter box with a row id")
    ep.add_argument("--range", default=None,
                    help="pre-fill the index-range box, e.g. '100-120' or '100'")
    ep.add_argument("--speaker", default=None,
                    help="pre-fill the Speaker filter box")
    ep.add_argument("--rebuild", action="store_true",
                    help="after the editor exits, re-apply the patch and write "
                         "a fresh release manifest (picks up saved "
                         "translations/overrides)")
    args = ap.parse_args()

    if args.sub == "edit":
        rc = run_edit(args.game, args.file, args.search, args.id,
                      args.range, args.speaker, args.rebuild)
        if not args.rebuild:
            sys.exit(rc)
        # --rebuild: the editor exited, so bake the saved state into the game.
        # Re-applying is the explicit purpose of the flag, so the already-
        # patched guard is bypassed and a fresh manifest is written afterwards.
        game = args.game or pick_game_dir()
        if not game:
            print("No game path provided; aborting.")
            sys.exit(1)
        sys.exit(rc or apply_patch(game, backup_dir=args.backup_dir,
                                   no_ui=args.no_ui,
                                   no_fix_sizes=args.no_fix_sizes,
                                   force=args.force,
                                   rebuild=True, reapply=True))

    game = pick_game_dir(args.game)
    if not game:
        print("No game path provided; aborting.")
        sys.exit(1)
    index = os.path.join(game, "data.i")
    backup_dir = args.backup_dir or os.path.join(game, "vietnam_backup")
    backup_index = os.path.join(backup_dir, "data.i")

    if args.restore:
        restore(game, index, backup_dir)
        sys.exit(0)

    # --rebuild: return to pristine state first, then re-apply from scratch.
    # The resulting install is by construction correct, so we finish by writing
    # a fresh manifest (verify --gen) instead of hash-checking the old one.
    if args.rebuild:
        if not os.path.isfile(backup_index):
            print(f"No backup in {backup_dir} - cannot rebuild a pristine state. "
                  "Run a normal patch first.")
            sys.exit(2)
        restore(game, index, backup_dir)
        args.skip_backup = True
        # Stamp the new build-VH before any load_translations() below runs, so
        # patch_install writes the fresh version row into the game tables
        # (gen_manifest alone would only record the old stamp afterwards).
        stamp = stamp_release(lambda: None)()
        print(f"Rebuild: restored to pristine state (stamp {stamp}).")

    sys.exit(apply_patch(game, backup_dir=backup_dir,
                         skip_backup=args.skip_backup,
                         no_ui=args.no_ui,
                         no_fix_sizes=args.no_fix_sizes,
                         force=args.force,
                         rebuild=args.rebuild))


if __name__ == "__main__":
    main()
