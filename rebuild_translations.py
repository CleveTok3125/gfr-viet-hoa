#!/usr/bin/env python3
"""Rebuild translations.json by diffing the pristine EN tables (extracted
from data.i) against the current Vietnamese ko/ tables.

Every row where EN != VI becomes an exact EN->VI entry. Rows where they are
equal (unchanged, e.g. proper nouns) are not emitted. Conflicts (same EN,
different VI) keep the most frequent VI and are reported for review.

This guarantees translations.json reproduces exactly the installed patch.

Usage:
    python3 rebuild_translations.py --game <install> [--en-ref <dir>] [--out <file>]
"""
import argparse
import collections
import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from common import bootstrap

bootstrap()
from common import repo_file
from game_version import game_version
from patch_engine import read_msg
from extract import extract

EN_PREFIX = "system/table/text/en"
VN_TEXT_DIR = "data/system/table/text/ko"
EN_SCENARIO_PREFIX = "system/table/scenario/en"
VN_SCENARIO_DIR = "data/system/table/scenario/ko"

# A couple of representative tables; their md5 fingerprints identify the build.
FINGERPRINT_FILES = ["text_ui.msg", "text.msg"]

TEXT_FILES = sorted(
    "text.msg text_badge.msg text_communication.msg text_dialog.msg "
    "text_fate_episode.msg text_limit_bonus.msg text_note.msg "
    "text_skillboard.msg text_stage.msg text_status.msg text_story.msg "
    "text_tutorial.msg text_ui.msg text_uskill.msg".split()
)


def scenario_files(game):
    """Return the non-tag scenario .msg files present in the install."""
    d = os.path.join(game, VN_SCENARIO_DIR)
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d)
                  if f.endswith(".msg") and not f.endswith("_tag.msg"))


def compute_fingerprint(game):
    fp = {}
    for f in FINGERPRINT_FILES:
        raw = extract(game, f"{EN_PREFIX}/{f}")
        if raw is not None:
            fp[f"{EN_PREFIX}/{f}"] = hashlib.md5(raw).hexdigest()
    return fp


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", required=True, help="path to a GBF Relink install")
    ap.add_argument("--en-ref", help="dir with pre-extracted EN .msg files "
                                     "(default: extract from data.i)")
    ap.add_argument("--out", default=repo_file("translations.json"))
    args = ap.parse_args()

    game = args.game
    if not os.path.isfile(os.path.join(game, "data.i")):
        print(f"data.i not found under {game!r}")
        sys.exit(1)

    merged = {}
    conflicts = []
    files = ([(f, EN_PREFIX, VN_TEXT_DIR) for f in TEXT_FILES] +
             [(f, EN_SCENARIO_PREFIX, VN_SCENARIO_DIR)
              for f in scenario_files(game)])
    for fname, en_prefix, vn_dir in files:
        if args.en_ref:
            raw = open(os.path.join(args.en_ref, fname), "rb").read()
        else:
            raw = extract(game, f"{en_prefix}/{fname}")
            if raw is None:
                print(f"  WARN: {fname} not found in this build - skipped")
                continue
        en = read_msg(raw)
        vn = read_msg(os.path.join(game, vn_dir, fname))
        rows = min(len(en["rows_"]), len(vn["rows_"]))
        table = merged.setdefault(fname, {})
        per_en = collections.defaultdict(collections.Counter)
        for i in range(rows):
            e = en["rows_"][i]["column_"]["text_"]
            v = vn["rows_"][i]["column_"]["text_"]
            if not isinstance(e, str) or not isinstance(v, str):
                continue
            if e != v:
                per_en[e][v] += 1
        for e, counters in per_en.items():
            vi, cnt = counters.most_common(1)[0]
            if len(counters) > 1:
                conflicts.append((fname, e, cnt, dict(counters)))
            table[e] = vi
        print(f"{fname}: en_rows={len(en['rows_'])} vn_rows={len(vn['rows_'])} "
              f"entries={len(table)}")

    total = sum(len(v) for v in merged.values())
    print("total entries:", total, "conflicts:", len(conflicts))
    for fname, e, cnt, others in conflicts[:20]:
        print("  CONFLICT", fname, repr(e[:50]), "kept", cnt,
              "others", {k: v for k, v in others.items()})

    out = {
        "meta": {
            "game": "Granblue Fantasy: Relink",
            "format": 1,
            "description": "EN->VI translation table keyed by exact string "
                           "found in .msg rows",
            "credits": {
                "scenario": "Scenario dialogue translation by TheRedTeam "
                            "(base game, before the Endless Ragnarok DLC)",
            },
            "disclaimer": "Additional translations beyond the TheRedTeam base "
                          "are machine/AI-generated; no responsibility for "
                          "their quality or for maintaining this project.",
        },
        "translations": merged,
    }
    ver = game_version(os.path.join(game, "granblue_fantasy_relink.exe"))
    if ver:
        out["meta"]["build"] = ver
    if not args.en_ref:
        fp = compute_fingerprint(game)
        if len(fp) == len(FINGERPRINT_FILES):
            out["meta"]["build_fingerprint"] = fp
            print("build_fingerprint:", fp)
        else:
            print("WARN: could not compute full build_fingerprint from", game)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
