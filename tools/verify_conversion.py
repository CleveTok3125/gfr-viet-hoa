#!/usr/bin/env python3
"""Verify the ID-keyed engine reproduces the exact same patch as the old
EN-keyed engine (+ rules.json node transforms), without touching the install.

For every row of every translated table the English source is extracted from
the game (data.i) and the patched ``text_`` is computed with:
  * old engine: EN-keyed translations + rules.json stat_map node transforms
  * new engine: ``src.patch_engine.PatchEngine`` (ID-keyed, no rules.json —
                stat lines are derived at runtime from the table itself)
The two effective text values must be identical row by row.

Usage:
    python3 tools/verify_conversion.py --game <install>
        [--old translations.json --new translations_new.json]
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from common import bootstrap, table_rel

bootstrap()
import msgpack

from extract import extract
from patch_engine import PatchEngine

SEP = "::"


def key_of(row_id, subid):
    return row_id if not subid else f"{row_id}{SEP}{subid}"


def en_path(file):
    rel = table_rel(file).replace("/ko", "/en")
    return rel[len("data/"):]


def rows_for(game, file):
    raw = extract(game, os.path.join(en_path(file), file))
    if raw is None:
        return None
    data = msgpack.unpackb(raw, raw=False)
    return [(r.get("column_", {}).get("id_hash_", ""),
             r.get("column_", {}).get("subid_hash_", ""),
             r.get("column_", {}).get("text_", ""))
            for r in data["rows_"]
            if isinstance(r.get("column_", {}).get("text_"), str)]


class OldEngine:
    def __init__(self, translations, rules):
        self.t = translations
        self.stat_map = (rules or {}).get("stat_map") or {}
        self.sb_files = set((rules or {}).get("skillboard_node_transform") or {}
                            .get("files", []))
        stats = list(self.stat_map)
        self.node_re = re.compile(r"^(.+?): ?\n(" +
                                  "|".join(re.escape(s) for s in stats) + r")$") \
            if stats else None

    def transform(self, file, text):
        tbl = self.t.get(file) or {}
        if text in tbl:
            return tbl[text]
        if self.node_re and file in self.sb_files:
            m = self.node_re.match(text)
            if m:
                return f"{m.group(1)}:\n{self.stat_map[m.group(2)]}"
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", required=True)
    ap.add_argument("--old", default="translations.json")
    ap.add_argument("--new", default="translations_new.json")
    args = ap.parse_args()

    with open(args.old, encoding="utf-8") as fh:
        old_doc = json.load(fh)
    with open(args.new, encoding="utf-8") as fh:
        new_doc = json.load(fh)
    rules = {}
    if os.path.isfile("rules.json"):
        with open("rules.json", encoding="utf-8") as fh:
            rules = json.load(fh)
    else:
        print("NOTE: rules.json gone (folded into id-keyed translations); "
              "old-engine skillboard node transform disabled.")

    old_eng = OldEngine(old_doc["translations"], rules)
    new_eng = PatchEngine(new_doc["translations"])

    files = sorted(set(old_doc["translations"]) | set(new_doc["translations"]))
    total = diffs = mismatched = 0
    for file in files:
        rows = rows_for(args.game, file)
        if rows is None:
            print(f"  WARN: {file} not found in build - skipped")
            continue
        stat_rule = new_eng._stat_rule(file, rows)
        for rid, subid, text in rows:
            total += 1
            o = old_eng.transform(file, text)
            n = new_eng.transform(file, rid, subid, text, stat_rule)
            # a row is only rewritten when the transform yields a value that
            # differs from the source; None or an identical value leave it as-is
            o_eff = o if (o is not None and o != text) else text
            n_eff = n if (n is not None and n != text) else text
            if o_eff != n_eff:
                diffs += 1
                if mismatched < 20:
                    def _s(x):
                        return repr((x or "")[:80])
                    print(f"DIFF {file} {key_of(rid, subid)!r}")
                    print(f"    en: {_s(text)}")
                    print(f"   old: {_s(o)}")
                    print(f"   new: {_s(n)}")
                mismatched += 1
    print(f"\nrows checked: {total}, diffs: {diffs}")
    print("OK - new ID-keyed engine is patch-identical" if diffs == 0
          else "FAILED - engines disagree on the patch output")
    sys.exit(1 if diffs else 0)


if __name__ == "__main__":
    main()