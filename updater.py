#!/usr/bin/env python3
"""Rebuild translations.json against a newer game build.

This is a thin wrapper around ``src/remap_ids.py``'s remapping engine:

  * rows whose stable id still exists are carried over unchanged;
  * rows whose id disappeared are fuzzy-remapped from the English snapshot
    (``data/._en_prev.json``) onto their new id and reported;
  * genuinely new rows are listed in ``review.txt`` for a fresh translation.

After a successful run the English snapshot is refreshed from the new build.

Writes:
    translations_new.json   candidate updated table (schema 2)
    review.txt              remapped / new rows that need a human look

Usage:
    python3 updater.py --game <new_install> [--out translations_new.json]
        [--snapshot data/._en_prev.json] [--accept 0.90] [--dry-run]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from common import bootstrap

bootstrap()
from common import repo_file
from remap_ids import ACCEPT, DEFAULT_SNAPSHOT, REVIEW, remap_file


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", required=True, help="path to the newer GBF Relink install")
    ap.add_argument("--out", default=None, help="output json path")
    ap.add_argument("--snapshot", default=DEFAULT_SNAPSHOT,
                    help="EN snapshot used for fuzzy remap and refreshed on write")
    ap.add_argument("--accept", type=float, default=ACCEPT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    game = args.game
    if not os.path.isfile(os.path.join(game, "data.i")):
        print(f"data.i not found under {game!r}")
        sys.exit(1)

    from common import load_translations

    doc = load_translations()
    snap = {}
    if os.path.isfile(args.snapshot):
        with open(args.snapshot, encoding="utf-8") as fh:
            snap = json.load(fh)

    new_trans = {}
    snap_new = {}
    counts = {"accepted": 0, "remap": 0, "review": 0, "new": 0, "skip": 0}
    review_lines = []
    for file, table in sorted(doc["translations"].items()):
        out, snap_file, report = remap_file(game, file, table, snap, accept=args.accept)
        if out is None:
            counts["skip"] += 1
            print(f"  SKIP {file}: table not found in this build")
            continue
        new_trans[file] = out
        snap_new[file] = snap_file
        for kind, key, new_en, matched, score in report:
            counts[kind] += 1
            if kind in ("remap", "review"):
                review_lines.append(
                    f"[{kind.upper()} {score}] {file} {key}\n"
                    f"  new: {new_en!r}\n  old: {matched!r}\n")
            elif kind == "new":
                review_lines.append(f"[NEW] {file} {key}\n  {new_en!r}\n")

    counts.pop("skip", None)
    print("counts:", counts)

    if args.dry_run:
        print("dry-run: nothing written")
        return 0

    if review_lines:
        with open("review.txt", "w", encoding="utf-8") as fh:
            fh.write("\n".join(review_lines))
        print(f"wrote review.txt ({len(review_lines)} rows)")

    from remap_ids import compute_fingerprint

    out_path = args.out or repo_file("translations_new.json")
    meta = dict(doc["meta"])
    fp = compute_fingerprint(game)
    if len(fp) == 2:
        meta["build_fingerprint"] = fp
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "translations": new_trans}, fh,
                  ensure_ascii=False, indent=1)
    print(f"wrote {out_path}")

    with open(args.snapshot, "w", encoding="utf-8") as fh:
        json.dump(snap_new, fh, ensure_ascii=False, indent=1)
    print(f"refreshed EN snapshot {args.snapshot}")


if __name__ == "__main__":
    main()
