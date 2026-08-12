#!/usr/bin/env python3
"""Verify patched files match the reference release manifest.

The manifest stores the md5 of every file produced by a good patch run
(data.i + the translated ko/ tables). Use it to detect a broken/failed
patch before launching the game.

Usage:
    python3 verify.py --game <install>            # check against manifest
    python3 verify.py --game <install> --gen      # write a fresh manifest

Exits 0 when everything matches, 1 otherwise.
"""

import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from common import bootstrap

bootstrap()

from common import load_translations, table_rel
from release_build import stamp_release

MANIFEST = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "release_manifest.json"
)


def patched_files():
    files = ["data.i"]
    for f in load_translations()["translations"]:
        files.append(os.path.join(table_rel(f), f))
        files.append(os.path.join(table_rel(f), f[: -len(".msg")] + "_tag.msg"))
    from patcher import ENGINE_FONT_PATHS, FONTS_ZIP

    if os.path.isfile(FONTS_ZIP):
        # The zip ships the font under its OFL name; at install time it is
        # written under the engine font paths (see patcher.install_fonts).
        for rel in ENGINE_FONT_PATHS:
            files.append("data/" + rel)
            files.append("data/" + os.path.join(
                os.path.dirname(rel),
                os.path.basename(rel)[: -len(".msg")] + "_1.wtb"))
    return files


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def gen_manifest(game_dir, out=MANIFEST):
    meta = load_translations()["meta"]
    manifest = {"build": meta.get("build", "?"), "files": {}}
    if meta.get("build_vh"):
        manifest["build_vh"] = meta["build_vh"]
    missing = []
    for rel in patched_files():
        p = os.path.join(game_dir, rel)
        if os.path.isfile(p):
            manifest["files"][rel] = md5(p)
        else:
            missing.append(rel)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    if missing:
        print(f"WARN: missing files not hashed: {missing}")
    print(f"Wrote manifest: {out} ({len(manifest['files'])} files)")


def verify(game_dir, manifest_path=MANIFEST):
    if not os.path.isfile(manifest_path):
        return None
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    mismatches = []
    for rel, expected in manifest["files"].items():
        p = os.path.join(game_dir, rel)
        if not os.path.isfile(p):
            mismatches.append((rel, expected, "<missing>"))
            continue
        actual = md5(p)
        if actual != expected:
            mismatches.append((rel, expected, actual))
    return mismatches


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", help="path to the GBF Relink install")
    ap.add_argument(
        "--gen",
        action="store_true",
        help="write a fresh manifest from this install instead of checking",
    )
    args = ap.parse_args()

    game = args.game
    if not game or not os.path.isfile(os.path.join(game, "data.i")):
        print("Pass --game <install> (or set GBFR_GAME).")
        sys.exit(1)

    if args.gen:
        stamp_release(gen_manifest)(game)
        sys.exit(0)

    mismatches = verify(game)
    if mismatches is None:
        print(
            "No manifest found. Run with --gen first to write one."
        )
        sys.exit(1)
    if mismatches:
        print(f"VERIFY FAILED: {len(mismatches)} file(s) differ from the reference:")
        for rel, exp, got in mismatches:
            print(f"  {rel}: expected {exp[:12]}... got {got[:12]}...")
        print("A previous patch may have failed; restore backups and re-apply.")
        sys.exit(1)
    print("Verify OK: all patched files match the reference manifest.")


if __name__ == "__main__":
    main()
