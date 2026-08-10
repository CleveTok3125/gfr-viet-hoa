#!/usr/bin/env python3
"""Build a speaker map for every scenario line from the game archive.

The scenario text tables (`system/table/scenario/{en,ko}/text_scenario_*.msg`)
only carry `id_hash_` + `text_`. The actual speaker is stored in the
language-neutral `system/table/scenario/scenario_*.msg` tables, which link
each sentence id to a `charaID_` (e.g. NP0000=Lyria, PL0000=Gran,
PL0100=Djeeta) plus a `voiceID_`.

This script extracts that mapping and writes `data/scenario_speakers.json`.

Run from repo root:
    PYTHONPATH=src:vendor python3 src/build_speaker_map.py [--game <install>]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import msgpack

from common import bootstrap

bootstrap()
from common import find_game_dir
from extract import extract


def scenario_nums(game, index_bytes):
    """Return the list of available scenario numbers by probing the archive.

    Rather than hard-coding the table list, we enumerate candidates up to a
    known upper bound and keep the ones that actually exist in data.i.
    """
    nums = []
    for n in range(1, 1000):
        if n in (210, 220, 230, 240, 250, 260, 270, 280, 290, 310):
            continue  # known gaps; probe would miss anyway
        num = f"{n:03d}"
        if extract(game, f"system/table/scenario/scenario_{num}.msg", index_bytes):
            nums.append(num)
    return nums


def load(game, index_bytes, internal):
    raw = extract(game, internal, index_bytes)
    if not raw:
        return None
    blob = msgpack.unpackb(raw, raw=False)
    if not isinstance(blob, dict) or "rows_" not in blob:
        return None
    return blob["rows_"]


def chara_names(game, index_bytes):
    """charaID -> (name_ko, name_en) from text_chara tables."""
    names = {}
    for lang in ("ko", "en"):
        rows = load(game, index_bytes, f"system/table/text/{lang}/text_chara.msg")
        if not rows:
            continue
        for r in rows:
            c = r["column_"]
            hid = c.get("id_hash_", "")
            if not hid.startswith("TXT_"):
                continue
            cid = hid[4:]
            entry = names.setdefault(cid, {})
            entry["name_" + lang] = c.get("text_", "")
    return names


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", default=None,
                    help="game directory (default: $GBFR_GAME or auto-detect)")
    ap.add_argument("--out", default=None, help="JSON output path")
    args = ap.parse_args()

    game = args.game or find_game_dir()
    if not game:
        sys.exit("Could not locate the game. Pass --game <path> or set GBFR_GAME.")
    index_path = os.path.join(game, "data.i")
    if not os.path.isfile(index_path):
        sys.exit(f"data.i not found at {index_path}")
    with open(index_path, "rb") as fh:
        index_bytes = fh.read()

    cnames = chara_names(game, index_bytes)
    nums = scenario_nums(game, index_bytes)
    print(f"game: {game}\nscenario files found: {len(nums)}")

    # 1) Collect sentenceID -> chara/voice/listener from scenario_*.msg
    speakers = {}
    for num in nums:
        rows = load(game, index_bytes, f"system/table/scenario/scenario_{num}.msg")
        if not rows:
            continue
        for r in rows:
            c = r["column_"]
            sid = c.get("sentenceID_hash_", "")
            if not sid:
                continue
            chara = c.get("charaID_", "")
            entry = {
                "chara": chara,
                "voice": c.get("voiceID_", ""),
                "listener": c.get("listener_", ""),
                "emotion": c.get("emotion_", ""),
                "name_ko": (cnames.get(chara, {}) or {}).get("name_ko", ""),
                "name_en": (cnames.get(chara, {}) or {}).get("name_en", ""),
            }
            speakers[sid] = entry

    out_path = args.out or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "scenario_speakers.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(speakers, fh, ensure_ascii=False, indent=1)
    print(f"wrote {len(speakers)} speaker entries -> {out_path}")


if __name__ == "__main__":
    main()
