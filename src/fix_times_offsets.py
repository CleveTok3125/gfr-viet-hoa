#!/usr/bin/env python3
"""Regenerate times_ voice-sync offsets in tag_tuning.json to VN positions.

The *_tag.msg tables carry `times_` markers (text-reveal / voice-sync pacing):
each holds time_ (seconds), wait_ and a character offset that indexes the
ORIGINAL (EN) string. Once the ko table is translated to Vietnamese the old
offsets point at the wrong character (or past the end), so the engine pauses
the dialogue text out of sync with the voice. This tool rewrites every
`times_` start_/end_ to the matching position in the Vietnamese text using
the EN->VN char map, exactly like the bolds_/colors_/words_/names_ spans.

Usage:
    python3 src/fix_times_offsets.py --game <install> [--write]
Without --write it only reports what would change.

The VN text is resolved from translations.json (EN -> VN); the EN text comes
from the game archive's en/ scenario+text tables (id_hash_ -> text_).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import bootstrap

bootstrap()

import msgpack

from extract import extract
from remap_tags import char_map, remap_times

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TUNING = os.path.join(HERE, "tag_tuning.json")
TRANSL = os.path.join(HERE, "translations.json")


def load_text_table(game, rel):
    raw = extract(game, rel)
    if not raw:
        return {}
    blob = msgpack.unpackb(raw, raw=False)
    return {r["column_"].get("id_hash_", ""): r["column_"].get("text_", "")
            for r in blob["rows_"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True, help="game directory")
    ap.add_argument("--write", action="store_true",
                    help="write changes back to tag_tuning.json")
    args = ap.parse_args()

    with open(TUNING, encoding="utf-8") as fh:
        data = json.load(fh)
    with open(TRANSL, encoding="utf-8") as fh:
        tr = json.load(fh)["translations"]

    total_changed = 0
    per_file = {}
    for base, entries in (data.get("files") or {}).items():
        # load EN reference table for this base
        if base.startswith("text_scenario"):
            rel = f"system/table/scenario/en/{base}.msg"
        else:
            rel = f"system/table/text/en/{base}.msg"
        en_text = load_text_table(args.game, rel)
        vn_table = tr.get(base + ".msg", {})
        changed = 0
        for rec in entries.values():
            if "times_" not in rec or not rec["times_"]:
                continue
            rid = rec.get("id_", "")
            en_txt = en_text.get(rid, "")
            if not en_txt:
                continue
            vn_txt = vn_table.get(en_txt, "")
            if not vn_txt or vn_txt == en_txt:
                continue
            m = char_map(en_txt, vn_txt)
            before = json.dumps(rec["times_"], ensure_ascii=False)
            changed += remap_times(vn_txt, rec["times_"], en_txt, m)
            after = json.dumps(rec["times_"], ensure_ascii=False)
            if before != after:
                pass
        if changed:
            per_file[base] = changed
            total_changed += changed

    for base, n in sorted(per_file.items()):
        print(f"{base}: {n} times_ marker(s) rewritten")
    print(f"TOTAL files touched: {len(per_file)}; markers rewritten: {total_changed}")

    if args.write and total_changed:
        tmp = TUNING + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, TUNING)
        print(f"wrote {TUNING}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
