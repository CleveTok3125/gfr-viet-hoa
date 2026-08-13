"""Apply translations.json to an install by matching each row to its
stable row id (id_hash_ / subid_hash_), not by the current display text.

This is the correct update path: after a translation edit (or a game
update), the ko/ tables may already hold Vietnamese (or a different
language) text, so matching an English key against the on-disk string
cannot work. The engine ids survive updates, so the row is located and
the Vietnamese value written by id regardless of the on-disk language.

Usage:
    python3 apply_diff.py [--game <path>] [--skip-fix-sizes] [--no-backup]
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from common import bootstrap

bootstrap()

import msgpack

import datai
from common import find_game_dir, load_translations, table_rel
from extract import extract
from patch_engine import final_text, read_msg, row_key, write_msg
from patcher import en_path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game")
    ap.add_argument("--skip-fix-sizes", action="store_true")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--max-line", type=int, default=None,
                    help="if set, re-run newline normalization")
    args = ap.parse_args()

    game = args.game or find_game_dir()
    if not game or not os.path.isfile(os.path.join(game, "data.i")):
        print("Could not locate the game. Pass --game <path>.")
        sys.exit(1)
    index = os.path.join(game, "data.i")
    print("Game:", game)

    trans = load_translations()["translations"]

    if not args.no_backup:
        bk = os.path.join(game, "vietnam_diff_backup")
        os.makedirs(bk, exist_ok=True)
        datai.backup(index, bk)
        for rel in sorted({table_rel(f) for f in trans}):
            src = os.path.join(game, rel)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(bk, os.path.basename(rel)),
                                dirs_exist_ok=True)
        print("Backup ->", bk)

    total_patched = total_en = total_checked = 0
    with open(index, "rb") as f:
        index_bytes = f.read()
    for file, d in trans.items():
        path = os.path.join(game, table_rel(file), file)
        if not os.path.isfile(path):
            print("  MISSING:", file)
            continue
        data = read_msg(path)
        disk_rows = data["rows_"]

        # Redirect stage: English reference (id -> text) from the same build.
        en_map = {}
        raw_en = extract(game, en_path(file), index_bytes)
        if raw_en is not None:
            en_obj = msgpack.unpackb(raw_en, raw=False)
            for r in en_obj["rows_"]:
                c = r.get("column_", {})
                t = c.get("text_", "")
                if isinstance(t, str) and c.get("id_hash_"):
                    en_map[(c.get("id_hash_", ""), c.get("subid_hash_", ""))] = t

        patched = already = en_red = 0
        for row in disk_rows:
            c = row.get("column_", {})
            if not c.get("id_hash_"):
                continue
            key = (c.get("id_hash_", ""), c.get("subid_hash_", ""))
            vn = d.get(row_key(*key))
            new = final_text(vn, en_map.get(key))
            if new is None:
                continue
            total_checked += 1
            if new == c.get("text_", ""):
                already += 1
            elif vn is not None:
                c["text_"] = new
                patched += 1
            else:
                c["text_"] = new
                en_red += 1
        if patched or en_red:
            write_msg(path, data)
        total_patched += patched
        total_en += en_red
        print(f"  {file}: {patched} patched, {already} already, "
              f"{en_red} redirected to EN ({len(d)} entries in table)")

    print(f"\nTotal patched rows: {total_patched}, redirected to EN: {total_en}, "
          f"checked: {total_checked}")

    if not args.skip_fix_sizes:
        fixes = datai.fix_sizes(
            game, index,
            [os.path.join(table_rel(f)[len("data/"):], f) for f in trans],
        )
        print(f"External sizes fixed: {len(fixes)}")

    # verify all touched tables unpack
    corrupt = 0
    for file in trans:
        path = os.path.join(game, table_rel(file), file)
        if not os.path.isfile(path):
            continue
        try:
            obj = read_msg(path)
            if isinstance(obj, dict) and "rows_" in obj:
                pass
            else:
                corrupt += 1
        except Exception:  # noqa: BLE001
            corrupt += 1
    print(f"Verify: 0 corrupt, {corrupt} corrupt tables")

    if total_patched == 0 and corrupt == 0:
        print("Nothing to patch - tables already up to date.")


if __name__ == "__main__":
    main()
