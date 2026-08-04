#!/usr/bin/env python3
"""Rip the full TheRedTeam translation out of the original installer.

The installer (a PyInstaller app) ships `Data.zip` containing the ko/ text and
scenario tables already translated to Vietnamese, plus the fonts and data.i.
We extract every ko/ table, align it to the English reference inside the game
archive by id_hash, and merge the resulting EN->VI pairs into
translations.json as an *addition-only* merge:

  * if an English string is already translated in translations.json, the
    existing (patched) translation wins - the rip never overwrites it;
  * strings the rip introduces are only added for English keys that are not
    yet present.

Usage:
    python3 rip_redteam.py --game <install> --zip <Data.zip> [--out translations.json]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from common import bootstrap, load_translations, repo_file, table_rel
bootstrap()
from extract import extract
import msgpack

DATA_ZIP = "/tmp/claude/opencode/GFRVH_260726.exe_extracted/Data.zip"


def en_path(file):
    """EN-source path inside data.i for a given table file."""
    rel = table_rel(file).replace("/ko", "/en")
    return rel[len("data/"):]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", required=True, help="path to a GBF Relink install")
    ap.add_argument("--zip", default=DATA_ZIP, help="path to the installer's Data.zip")
    ap.add_argument("--out", default=None, help="output json path")
    args = ap.parse_args()

    import zipfile
    zf = zipfile.ZipFile(args.zip)

    game = args.game
    index_bytes = open(os.path.join(game, "data.i"), "rb").read()

    trans = load_translations()
    merged = {f: dict(m) for f, m in trans["translations"].items()}

    stats = {"added": 0, "skipped_existing": 0, "identity": 0, "files": 0}
    added_files = []

    for info in zf.infolist():
        name = info.filename
        if not name.endswith(".msg") or "/ko/" not in name or name.endswith("_tag.msg"):
            continue
        rel = name[name.index("system/"):]
        file = rel.rsplit("/", 1)[-1]

        ko_raw = zf.read(name)
        ko = msgpack.unpackb(ko_raw, raw=False)

        en_raw = extract(game, os.path.join(en_path(file), file), index_bytes)
        if en_raw is None:
            print(f"  WARN: {en_path(file)}/{file} not in game archive - skipped")
            continue
        en = msgpack.unpackb(en_raw, raw=False)

        table = merged.setdefault(file, {})
        if file not in trans["translations"]:
            added_files.append(file)

        # Align rows by id_hash/subid_hash to get EN->VI pairs robustly.
        by_id = {}
        for r in en["rows_"]:
            c = r["column_"]
            key = (c.get("id_hash_", ""), c.get("subid_hash_", ""))
            by_id[key] = c.get("text_", "")

        for r in ko["rows_"]:
            c = r["column_"]
            key = (c.get("id_hash_", ""), c.get("subid_hash_", ""))
            en_txt = by_id.get(key)
            if en_txt is None:
                continue
            vi_txt = c.get("text_", "")
            if en_txt in table:
                stats["skipped_existing"] += 1
                continue
            if en_txt == vi_txt:
                # TheRedTeam kept this row in English (proper nouns, numbers,
                # untranslated terms). On a pristine install the ko/ archive
                # table holds Korean, so we must still map EN->EN to replace it.
                table[en_txt] = en_txt
                stats["identity"] += 1
                continue
            table[en_txt] = vi_txt
            stats["added"] += 1

        stats["files"] += 1

    # Rebuild meta with provenance of the ripped translation.
    meta = dict(trans.get("meta", {}))
    meta["redteam_merge"] = {
        "source": "TheRedTeam installer Data.zip (ko/ tables)",
        "addition_only": True,
        "files_processed": stats["files"],
        "entries_added": stats["added"],
        "entries_skipped_existing": stats["skipped_existing"],
        "identity_entries_added": stats["identity"],
        "new_files": added_files,
    }

    out_path = args.out or repo_file("translations.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "translations": merged}, f,
                  ensure_ascii=False, indent=1)

    print(f"Files processed      : {stats['files']}")
    print(f"Entries added        : {stats['added']}")
    print(f"Skipped (exists)     : {stats['skipped_existing']}")
    print(f"Identity (EN==VI)    : {stats['identity']}")
    print(f"New files introduced : {len(added_files)}")
    print(f"Total files now      : {len(merged)}")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
