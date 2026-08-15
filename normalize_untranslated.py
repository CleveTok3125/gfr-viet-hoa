#!/usr/bin/env python3
"""Clear stored rows that are not real Vietnamese translations.

Two kinds of stored values are emptied:

1. *Exact matches*: the stored value equals the game's English text 1-1
   (whitespace-normalized, case-sensitive -- safety first).
2. *English prose*: the stored value is prose-length (>= 40 chars) with no
   Vietnamese diacritics (``tr_edit_core.tr_state`` == "en") and the game's
   English reference exists. Such rows are English-looking and not translated
   yet; many also carry encoding-corrupted copies of the English text
   (``\\x81\\u060c`` instead of ``↓``, ``c`` instead of ``©``).

Clearing is safe for both kinds because the patcher treats an empty stored
translation as "no translation" and falls back to the game's own English text
(verified: every cleared prose row has a non-empty English reference), so the
on-screen text is unchanged or actually cleaned up while the editor honestly
flags the row as untranslated.

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

from tr_edit_core import tr_state

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
        description="Clear stored values that are not real translations "
                    "(exact VN=EN matches and English-looking prose).")
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

    total_exact = 0
    total_prose = 0
    per_file = {}
    for file, tbl in translations.items():
        en = en_src.get(file, {})
        cleared_exact = 0
        cleared_prose = 0
        for key, vn in tbl.items():
            vs = norm(vn)
            if not vs:
                continue
            es = norm(en.get(key))
            if es and vs == es:
                tbl[key] = ""
                cleared_exact += 1
                continue
            if es and tr_state(vn) == "en":
                tbl[key] = ""
                cleared_prose += 1
        n = cleared_exact + cleared_prose
        if n:
            per_file[file] = (cleared_exact, cleared_prose, n)
            total_exact += cleared_exact
            total_prose += cleared_prose

    total = total_exact + total_prose
    if args.write:
        backup = TRANS_PATH + ".bak"
        with open(TRANS_PATH, encoding="utf-8") as fh, \
                open(backup, "w", encoding="utf-8") as bh:
            bh.write(fh.read())
        with open(TRANS_PATH, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
        print(f"wrote {TRANS_PATH}: {total} rows cleared "
              f"({total_exact} exact, {total_prose} prose; backup: {backup})")
    else:
        print(f"dry-run: {total} rows across {len(per_file)} files would be "
              f"cleared ({total_exact} exact, {total_prose} prose)")

    for f, (ex, pr, n) in sorted(per_file.items(), key=lambda x: -x[1][2]):
        kind = "exact" if ex and not pr else ("prose" if pr and not ex
                                              else f"{ex} exact + {pr} prose")
        print(f"  {f}: {n} ({kind})")


if __name__ == "__main__":
    main()