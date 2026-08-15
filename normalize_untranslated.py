#!/usr/bin/env python3
"""Clear rows whose stored Vietnamese equals the English reference.

A stored value that matches the game's English text 1-1 (after whitespace
normalization) is not really a translation: at patch time the EN-redirect
stage already shows that English text, so the row carries no Vietnamese
value at all. Clearing it keeps the data honest (the editor flags it as
untranslated) without changing what the game displays, because the patcher
treats an empty stored translation as "no translation" and falls back to
English.

The comparison is deliberately strict and case-sensitive: only exact 1-1
matches are cleared (safety first).

EN source: the game install (--game, authoritative) when given, otherwise
the local English snapshot data/._en_prev.json. Nothing is written unless
--write is passed.

Run from the repo root:
    python3 normalize_untranslated.py            # dry-run report
    python3 normalize_untranslated.py --write    # apply
"""
import argparse
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
for p in (REPO, os.path.join(REPO, "src"), os.path.join(REPO, "vendor")):
    if p not in sys.path:
        sys.path.insert(0, p)

TRANS_PATH = os.path.join(REPO, "translations.json")
DEFAULT_SNAPSHOT = os.path.join(REPO, "data", "._en_prev.json")
NORM_RE = re.compile(r"\s+")


def norm(s):
    """Collapse all whitespace and strip; exact 1-1 comparison afterwards."""
    return NORM_RE.sub(" ", s or "").strip()


def load_en(args):
    """Return {file: {row_key: en_text}} from the game or the snapshot."""
    if args.game:
        from tr_edit_core import Store
        store = Store(game_dir=args.game)
        return {f: store.id_text_map(f) for f in store.tables}
    if os.path.isfile(args.snapshot):
        with open(args.snapshot, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def main():
    ap = argparse.ArgumentParser(
        description="Clear stored translations that equal the English text.")
    ap.add_argument("--game", help="game install dir (authoritative EN source)")
    ap.add_argument("--snapshot", default=DEFAULT_SNAPSHOT,
                    help="EN snapshot fallback (default: data/._en_prev.json)")
    ap.add_argument("--write", action="store_true",
                    help="write translations.json (default: report only)")
    args = ap.parse_args()

    with open(TRANS_PATH, encoding="utf-8") as fh:
        doc = json.load(fh)
    translations = doc["translations"]

    en_src = load_en(args)
    if en_src is None:
        print("No EN source: pass --game or provide the snapshot; aborting.")
        sys.exit(2)

    total = 0
    per_file = {}
    for file, tbl in translations.items():
        en = en_src.get(file, {})
        cleared = 0
        for key, vn in tbl.items():
            vs = norm(vn)
            if not vs:
                continue
            es = norm(en.get(key))
            if es and vs == es:
                tbl[key] = ""
                cleared += 1
        if cleared:
            per_file[file] = cleared
            total += cleared

    if args.write:
        backup = TRANS_PATH + ".bak"
        with open(TRANS_PATH, encoding="utf-8") as fh, \
                open(backup, "w", encoding="utf-8") as bh:
            bh.write(fh.read())
        with open(TRANS_PATH, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
        print(f"wrote {TRANS_PATH}: {total} rows cleared "
              f"(backup: {backup})")
    else:
        print(f"dry-run: {total} rows across {len(per_file)} files would "
              f"be cleared")

    for f, n in sorted(per_file.items(), key=lambda x: -x[1]):
        print(f"  {f}: {n}")


if __name__ == "__main__":
    main()