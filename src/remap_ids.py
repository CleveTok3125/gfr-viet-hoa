#!/usr/bin/env python3
"""Remap id-keyed translations onto a newer game build.

Matching strategy, per row of the newer build's English table:

  * exact row id (``id_hash_`` / ``id_hash_::subid_hash_``) already present in
    the current table        -> translation carried over unchanged;
  * id disappeared (the game renamed/rewrote the row) -> the new build's
    English text is fuzzy-matched (difflib) against the last-known English
    snapshot (``data/._en_prev.json``), restricted to snapshot keys that carry
    a translation today; a high-confidence hit moves the VN onto the new id
    and is reported as REMAP;
  * review range (accept..review) -> reported, not applied;
  * nothing matches               -> reported as NEW.

After a successful run the English snapshot is refreshed from the new build so
the next run compares against the current English.

The remapping core is ``remap_file``; tools such as ``scripts/updater.py``
reuse it.

Usage:
    python3 src/remap_ids.py --game <install>
        [--out translations_new.json] [--snapshot data/._en_prev.json]
        [--accept 0.90] [--dry-run]
"""
import argparse
import difflib
import hashlib
import json
import os
import sys
from datetime import date

import msgpack

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from common import bootstrap

bootstrap()
from common import repo_file, table_rel
from extract import extract
from patch_engine import row_key

ACCEPT = 0.90
REVIEW = 0.80
DEFAULT_SNAPSHOT = os.path.join("data", "._en_prev.json")

FINGERPRINT_FILES = ["text_ui.msg", "text.msg"]


def en_path(file):
    """EN-source path inside data.i for a given table file."""
    rel = table_rel(file).replace("/ko", "/en")
    return rel[len("data/"):]


def load_file_rows(game, file):
    """Return ``[(id_hash_, subid_hash_, text_)]`` for the EN table, or None."""
    raw = extract(game, os.path.join(en_path(file), file))
    if raw is None:
        return None
    data = msgpack.unpackb(raw, raw=False)
    return [(r.get("column_", {}).get("id_hash_", ""),
             r.get("column_", {}).get("subid_hash_", ""),
             r.get("column_", {}).get("text_", ""))
            for r in data["rows_"]
            if isinstance(r.get("column_", {}).get("text_"), str)]


def remap_file(game, file, table, snap, accept=ACCEPT, review=REVIEW):
    """Remap one table.

    Returns ``(out_keys, snapshot_keys, report)`` where:
      * ``out``      ``{key: vn}`` for the new build (carried + remapped),
      * ``snap``     ``{key: en}`` of the new build's full EN table,
      * ``report``   list of ``(kind, key, new_en, matched_en, score)``
    """
    rows = load_file_rows(game, file)
    if rows is None:
        return None, None, []

    out = {}
    report = []
    snap_file = {}

    snap_pool = {}
    for key, en in (snap.get(file) or {}).items():
        if key in table:
            snap_pool.setdefault(en, []).append(key)
    phrases = list(snap_pool)

    accepted = remapped = reviewed = new = 0
    for rid, sub, text in rows:
        key = row_key(rid, sub)
        snap_file[key] = text
        if key in table:
            out[key] = table[key]
            accepted += 1
            continue
        if not text or not phrases:
            new += 1
            report.append(("new", key, text, "", 0.0))
            continue
        best = difflib.get_close_matches(text, phrases, n=1, cutoff=review)
        if not best:
            new += 1
            report.append(("new", key, text, "", 0.0))
            continue
        phrase = best[0]
        score = difflib.SequenceMatcher(None, text, phrase).ratio()
        old_key = snap_pool[phrase][0]
        if score >= accept:
            out[key] = table[old_key]
            remapped += 1
            report.append(("remap", key, text, phrase, round(score, 3)))
        else:
            reviewed += 1
            report.append(("review", key, text, phrase, round(score, 3)))
    return out, snap_file, report


def compute_fingerprint(game):
    fp = {}
    for f in FINGERPRINT_FILES:
        raw = extract(game, f"{en_path(f)}/{f}")
        if raw is not None:
            fp[f"system/table/text/en/{f}"] = hashlib.md5(raw).hexdigest()
    return fp


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", required=True, help="path to the newer GBF Relink install")
    ap.add_argument("--out", default=None, help="output json path")
    ap.add_argument("--snapshot", default=DEFAULT_SNAPSHOT,
                    help="EN snapshot used for fuzzy remap and refreshed on write")
    ap.add_argument("--accept", type=float, default=ACCEPT)
    ap.add_argument("--review", type=float, default=REVIEW)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    game = args.game
    if not os.path.isfile(os.path.join(game, "data.i")):
        print(f"data.i not found under {game!r}")
        sys.exit(1)

    from common import load_translations
    from game_version import game_version

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
        out, snap_file, report = remap_file(game, file, table, snap,
                                            accept=args.accept, review=args.review)
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
        with open(os.path.join(os.getcwd(), "review.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(review_lines))
        print(f"wrote review.txt ({len(review_lines)} rows)")

    out_path = args.out or repo_file("translations_new.json")
    meta = dict(doc["meta"])
    meta["date"] = date.today().isoformat()
    ver = game_version(os.path.join(game, "granblue_fantasy_relink.exe"))
    if ver:
        meta["build"] = ver
    fp = compute_fingerprint(game)
    if len(fp) == len(FINGERPRINT_FILES):
        meta["build_fingerprint"] = fp
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "translations": new_trans}, fh,
                  ensure_ascii=False, indent=1)
    print(f"wrote {out_path}")

    with open(args.snapshot, "w", encoding="utf-8") as fh:
        json.dump(snap_new, fh, ensure_ascii=False, indent=1)
    print(f"refreshed EN snapshot {args.snapshot}")


if __name__ == "__main__":
    sys.exit(main())