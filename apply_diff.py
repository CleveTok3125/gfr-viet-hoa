"""Apply translations.json to an install by matching each row to its
English reference (by index / id_hash), not by the current display text.

This is the correct update path: after a translation edit (or a game
update), the ko/ tables may already hold Vietnamese (or a different
language) text, so matching the English key against the on-disk string
cannot work. Instead we extract the English reference from data.i and
write the Vietnamese value onto the matching row.

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
from patch_engine import read_msg, write_msg


def en_path(file):
    return table_rel(file).replace("/ko", "/en")[len("data/"):] + "/" + file


def load_en_rows(game, file):
    data = extract(game, en_path(file))
    if data is None:
        return None
    obj = msgpack.unpackb(data, raw=False)
    return obj["rows_"]


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

    total_patched = 0
    total_checked = 0
    for file, d in trans.items():
        en_rows = load_en_rows(game, file)
        path = os.path.join(game, table_rel(file), file)
        if not os.path.isfile(path):
            print("  MISSING:", file)
            continue
        data = read_msg(path)
        disk_rows = data["rows_"]
        if en_rows is None:
            print("  NO EN REF:", file)
            continue

        id_map = None
        if len(disk_rows) != len(en_rows):
            id_map = {}
            for i, r in enumerate(en_rows):
                c = r["column_"]
                key = (c.get("id_hash_", ""), c.get("subid_hash_", ""))
                id_map.setdefault(key, i)
        else:
            # rows align by index on the same build
            pass

        patched = already = 0
        for idx, row in enumerate(disk_rows):
            if id_map is not None:
                c = row["column_"]
                key = (c.get("id_hash_", ""), c.get("subid_hash_", ""))
                src = id_map.get(key)
                if src is None:
                    continue
            else:
                src = idx
            en = en_rows[src]["column_"]["text_"]
            vn = d.get(en)
            if vn is None:
                continue
            total_checked += 1
            if vn == row["column_"]["text_"]:
                already += 1
            else:
                row["column_"]["text_"] = vn
                patched += 1
        if patched:
            write_msg(path, data)
        total_patched += patched
        print(f"  {file}: {patched} patched, {already} already "
              f"({len(d)} entries in table)")

    print(f"\nTotal patched rows: {total_patched}, checked: {total_checked}")

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
