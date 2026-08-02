#!/usr/bin/env python3
"""Rebuild translations.json against a newer game build.

Usage:
    python3 updater.py --game <new_install> [--out translations_new.json]

For every text table, the English source is extracted from the new data.i and
each unique string is matched against the current table:
  * exact match      -> translation carried over
  * high-confidence  -> difflib ratio >= 0.95, added automatically
  * fuzzy match      -> 0.90..0.95, written to review.txt for confirmation
  * no match         -> listed in review.txt as needing a new translation

Writes:
    translations_new.json   candidate updated table
    review.txt              strings that need human review / translation
"""
import argparse
import difflib
import json
import os
import sys

import msgpack

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from common import bootstrap
bootstrap()
from common import load_translations, repo_file, table_rel
from game_version import game_version
from extract import extract

FUZZY_ACCEPT = 0.95
FUZZY_REVIEW = 0.90


def en_path(file):
    """EN-source path inside data.i for a given table file."""
    rel = table_rel(file).replace("/ko", "/en")
    return rel[len("data/"):]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", required=True, help="path to the newer GBF Relink install")
    ap.add_argument("--out", default=None, help="output json path")
    args = ap.parse_args()

    game = args.game
    if not os.path.isfile(os.path.join(game, "data.i")):
        print(f"data.i not found under {game!r}")
        sys.exit(1)

    trans = load_translations()["translations"]
    new_trans = {f: dict(m) for f, m in trans.items()}

    review = []
    stats = {"exact": 0, "accepted": 0, "fuzzy": 0, "missing": 0}

    for file, table in trans.items():
        path = os.path.join(en_path(file), file)
        raw = extract(game, path)
        if raw is None:
            print(f"  WARN: {path} not found in this build - skipped")
            continue
        data = msgpack.unpackb(raw, raw=False)
        strings = {r["column_"]["text_"] for r in data["rows_"]
                   if isinstance(r.get("column_", {}).get("text_"), str)}

        if not strings:
            print(f"  {file}: no strings?")
            continue

        known = set(table)
        exact = strings & known
        stats["exact"] += len(exact)

        unknown = strings - known
        for seq in sorted(unknown):
            pool = [k for k in table if abs(len(k) - len(seq)) <= max(4, 0.25 * len(seq))]
            match = difflib.get_close_matches(seq, pool, n=1, cutoff=FUZZY_REVIEW)
            if not match:
                stats["missing"] += 1
                review.append(f"[NEW] {file}\n  {seq!r}\n")
                continue
            best, score = match[0], None
            sm = difflib.SequenceMatcher(None, seq, best)
            score = sm.ratio()
            if score >= FUZZY_ACCEPT:
                new_trans[file][seq] = table[best]
                stats["accepted"] += 1
                review.append(f"[ACCEPTED {score:.3f}] {file}\n  {seq!r} -> {table[best]!r}\n")
            else:
                stats["fuzzy"] += 1
                review.append(
                    f"[REVIEW {score:.3f}] {file}\n  {seq!r}\n  suggestion: {table[best]!r}\n")

    out_path = args.out or repo_file("translations_new.json")
    meta = {
        "game": "Granblue Fantasy: Relink",
        "format": 1,
        "description": "EN->VI translation table (updater output, review before release)",
    }
    ver = game_version(os.path.join(game, "granblue_fantasy_relink.exe"))
    if ver:
        meta["build"] = ver
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "translations": new_trans}, f,
                  ensure_ascii=False, indent=1)
    with open(os.path.join(os.path.dirname(out_path), "review.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(review))

    print(f"Strings matched exactly : {stats['exact']}")
    print(f"Accepted (>= {FUZZY_ACCEPT}) : {stats['accepted']}")
    print(f"Need review (0.90..{FUZZY_ACCEPT}): {stats['fuzzy']}")
    print(f"New (untranslated)      : {stats['missing']}")
    print(f"Wrote {out_path} and review.txt")


if __name__ == "__main__":
    main()
