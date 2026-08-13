#!/usr/bin/env python3
"""Convert translations.json from EN-text keys to stable row-ID keys.

Every translated table's English source is extracted from the game (data.i)
and each row is mapped by (id_hash_, subid_hash_). The Vietnamese value is
looked up from the old EN-keyed table:

    old:  translations = { file: { <en_text>: <vn> } }
    new:  translations = { file: { <id> | <id>::<subid>: <vn> } }

Entries whose Vietnamese equals the row's English text (identity) are
dropped: they produce no change when patched and would only reintroduce game
text into the repository.

Also writes data/._en_prev.json — a gitignored English snapshot
(file -> key -> en) used later by updater.py for fuzzy remapping after a game
update. It is never committed.

Usage:
    python3 tools/convert_to_id_keys.py --game <install>
        [--in translations.json] [--out translations_new.json]
"""
import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from common import bootstrap, table_rel

bootstrap()
import msgpack

from extract import extract

SEP = "::"


def key_of(row_id, subid):
    """Stable dict key for a row: id alone, or id::subid when split."""
    return row_id if not subid else f"{row_id}{SEP}{subid}"


def en_path(file):
    rel = table_rel(file).replace("/ko", "/en")
    return rel[len("data/"):]


def rows_for(game, file):
    """Yield (id, subid, text) for every string row of an EN table."""
    raw = extract(game, os.path.join(en_path(file), file))
    if raw is None:
        return None
    data = msgpack.unpackb(raw, raw=False)
    out = []
    for r in data["rows_"]:
        c = r.get("column_", {}) or {}
        tx = c.get("text_")
        if not isinstance(tx, str):
            continue
        out.append((c.get("id_hash_", ""), c.get("subid_hash_", ""), tx))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", required=True, help="GBF Relink install dir (data.i)")
    ap.add_argument("--in", dest="inp", default="translations.json")
    ap.add_argument("--out", default="translations_new.json")
    ap.add_argument("--en-snapshot", default="data/._en_prev.json")
    args = ap.parse_args()

    game = args.game
    if not os.path.isfile(os.path.join(game, "data.i")):
        print(f"data.i not found under {game!r}")
        sys.exit(1)
    if not os.path.isfile(args.inp):
        print(f"input translations not found: {args.inp}")
        sys.exit(1)

    with open(args.inp, encoding="utf-8") as fh:
        old = json.load(fh)
    old_table = old.get("translations", {})
    meta = dict(old.get("meta", {}))
    meta["schema"] = 2
    meta["description"] = ("VI translation table keyed by stable row ids "
                           "(id_hash_ or id_hash_::subid_hash_)")
    meta.pop("redteam_merge", None)
    meta.pop("credits", None)
    meta["disclaimer"] = ("Translation built on TheRedTeam's base and may "
                          "diverge over time. Legit-install-only patch; no "
                          "DRM bypass; do not redistribute patched game files.")

    new_table = {}
    en_snap = {}
    total_old = 0
    total_new = 0
    identity = 0
    stale = []
    errors = []

    for file, table in old_table.items():
        rows = rows_for(game, file)
        if rows is None:
            print(f"  WARN: {file} not found in this build - carried over unchanged")
            new_table[file] = dict(table)
            total_new += len(table)
            continue
        by_en = {}
        for rid, subid, tx in rows:
            key = key_of(rid, subid)
            if SEP in rid:
                errors.append(f"{file}: id {rid!r} contains {SEP!r} - key collision")
                continue
            by_en.setdefault(tx, []).append(key)
        new_tbl = {}
        for rid, subid, tx in rows:
            en_snap.setdefault(file, {})[key_of(rid, subid)] = tx
            vn = table.get(tx)
            if vn is None:
                continue
            total_old += 1
            if vn == tx:
                identity += 1
                continue
            new_tbl[key_of(rid, subid)] = vn
        total_new += len(new_tbl)
        new_table[file] = new_tbl
        # stale EN keys: present in the old table but not in this build
        for en_key in table:
            if en_key not in by_en:
                stale.append((file, en_key))
        print(f"  {file}: rows={len(rows)} old={len(table)} "
              f"new={len(new_tbl)} (identity-dropped={identity})")

    meta["converted"] = {
        "old_entries": total_old,
        "new_entries": total_new,
        "identity_dropped": identity,
        "stale_entries": len(stale),
    }

    out = {"meta": meta, "translations": new_table}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    os.makedirs(os.path.dirname(args.en_snapshot), exist_ok=True)
    with open(args.en_snapshot, "w", encoding="utf-8") as fh:
        json.dump(en_snap, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    fp = {}
    for f in ("text_ui.msg", "text.msg"):
        raw = extract(game, f"system/table/text/en/{f}")
        if raw is not None:
            fp[f"system/table/text/en/{f}"] = hashlib.md5(raw).hexdigest()
    if len(fp) == 2:
        out["meta"]["build_fingerprint"] = fp

    print(f"\nold entries: {total_old}")
    print(f"new entries: {total_new}")
    print(f"identity dropped: {identity}")
    print(f"stale EN keys (not in this build): {len(stale)}")
    for f, k in stale[:10]:
        print(f"   stale {f}: {k[:60]!r}")
    if errors:
        print("ERRORS:")
        for e in errors:
            print("  ", e)
        sys.exit(2)
    print(f"wrote {args.out}")
    print(f"wrote EN snapshot {args.en_snapshot} (gitignored)")


if __name__ == "__main__":
    main()
