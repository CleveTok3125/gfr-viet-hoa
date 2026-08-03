#!/usr/bin/env python3
"""Interactive review tool for *_tag.msg highlight ranges.

Runs the remap analysis over every tag file and walks the human through
each range that could not be resolved exactly. For every entry it shows
the English source span, the Vietnamese text with the current estimate
highlighted, and asks for the correct VN character range.

Answers typed on stdin are stored in tag_overrides.json (git-tracked),
which src/remap_tags.py applies verbatim when --overrides is given.

Per-entry input (each answer is written immediately):
    start,end         exact VN range, e.g. 12,25
    <enter>           accept the estimated range
    <word>            type a VN word/phrase to locate (uses its span)
    s                 skip this entry (leave untouched)
    q                 quit now (progress saved)

Usage:
    python3 -m src.tag_review --game <dir> [--overrides tag_overrides.json]
"""
import argparse
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, ".."))

from common import bootstrap  # noqa: E402
bootstrap()

from remap_tags import (  # noqa: E402
    build_id_text, char_map, find_in_vn, remap_range, TEXT_KO, SCENARIO_KO)


def show_vn(vn_text, s, e, width=60):
    """Print vn_text with [s:e) bracketed, wrapped, with caret markers."""
    lines = vn_text.split("\n")
    out = []
    offset = 0
    for ln in lines:
        start = max(s - offset, 0)
        end = min(e - offset, len(ln))
        mark = ""
        for i in range(len(ln)):
            if start <= i < end:
                mark += "^"
            elif len(mark) > 0 and i == len(ln) - 1:
                pass
            else:
                mark += " "
        if len(mark) < len(ln):
            mark = mark.ljust(len(ln))
        out.append(ln)
        out.append(mark)
        offset += len(ln) + 1
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True, help="game directory")
    ap.add_argument("--overrides", default="tag_overrides.json",
                    help="output JSON of manual VN ranges")
    ap.add_argument("--only", default=None,
                    help="comma-separated file basenames to review (default all)")
    args = ap.parse_args()

    game = args.game
    only = set(args.only.split(",")) if args.only else None

    import glob
    from remap_tags import load_tag, save_tag
    from extract import extract
    import msgpack

    overrides = {}
    if os.path.exists(args.overrides):
        with open(args.overrides, "r", encoding="utf-8") as fh:
            overrides = json.load(fh)

    bases = []
    for d in (TEXT_KO, SCENARIO_KO):
        for p in sorted(glob.glob(os.path.join(game, d, "*_tag.msg"))):
            b = os.path.basename(p)
            if b.endswith("_tag.msg"):
                base = b[: -len("_tag.msg")]
                if only is None or base in only:
                    bases.append(base)
    bases = sorted(set(bases))

    total_entries = 0
    reviewed = 0
    written = 0
    quit_now = False

    for base in bases:
        if base.startswith("text_scenario"):
            dir_rel = SCENARIO_KO
            en_dir = "system/table/scenario/en"
        else:
            dir_rel = TEXT_KO
            en_dir = "system/table/text/en"

        ko_tag_path = os.path.join(game, dir_rel, base + "_tag.msg")
        if not os.path.exists(ko_tag_path):
            continue

        tag_blob = load_tag(ko_tag_path)
        en_path = os.path.join(en_dir, base + ".msg")
        en_bytes = extract(game, en_path)
        en_text = build_id_text(msgpack.unpackb(en_bytes, raw=False)) if en_bytes else {}
        vn_path = os.path.join(game, dir_rel, base + ".msg")
        if not os.path.exists(vn_path):
            continue
        vn_text = msgpack.unpackb(open(vn_path, "rb").read(), raw=False)
        vn_by_id = build_id_text(vn_text)

        # Build the same EN tag index used by remap_tags for ground truth.
        en_tag_path = os.path.join(en_dir, base + "_tag.msg")
        en_tag_bytes = extract(game, en_tag_path)
        if not en_tag_bytes:
            continue
        en_tag = msgpack.unpackb(en_tag_bytes, raw=False)
        en_by_id = {}
        for entry in en_tag["Tag"]["tags_"]:
            el = entry["Element"]
            en_by_id[(el.get("id_", ""), el.get("subid_", ""))] = el

        file_over = overrides.setdefault(base, {})
        file_entries = 0
        for entry in tag_blob["Tag"]["tags_"]:
            el = entry["Element"]
            rid = el.get("id_", "")
            subid = el.get("subid_", "")
            en_el = en_by_id.get((rid, subid))
            vn_txt = vn_by_id.get((rid, subid), "")
            if not vn_txt or en_el is None:
                continue
            en_txt = en_text.get((rid, subid), "")
            if not en_txt:
                continue
            m = char_map(en_txt, vn_txt)
            id_over = file_over.setdefault(rid, {})
            for key in ("bolds_", "colors_", "words_", "names_"):
                items = el.get(key)
                if not items:
                    continue
                src_items = en_el.get(key, [])
                for n, item in enumerate(items):
                    if n >= len(src_items):
                        continue
                    src = src_items[n]["Element"]
                    try:
                        start = int(src["start_"])
                        end = int(src["end_"])
                    except (KeyError, ValueError, TypeError):
                        continue
                    # only offer entries that were not resolved exactly
                    new = remap_range(en_txt, vn_txt, m, start, end)
                    if new is not None and new[0] is not None and \
                            new[2] in ("exact", "found", "marker", "match"):
                        continue
                    total_entries += 1
                    file_entries += 1
                    sub_en = en_txt[start:end]
                    cur = (new[0], new[1]) if new and new[0] is not None else (None, None)
                    if file_over.get(key, {}).get(str(n)):
                        continue  # already manually set earlier
                    print("\n" + "=" * 70)
                    print(f"[{base}] id={rid} {key}[{n}]  EN index [{start}:{end}]")
                    print(f"EN span: {sub_en!r}")
                    print("EN full: " + en_txt.replace("\n", "\\n"))
                    print("--- VN text (estimate bracketed) ---")
                    if cur[0] is not None:
                        print(show_vn(vn_txt, cur[0], cur[1]))
                    else:
                        print(vn_txt)
                    while True:
                        try:
                            ans = input(f"VN range (cur {cur[0]},{cur[1]})> ").strip()
                        except EOFError:
                            print("\nEOF - saving and exiting.")
                            quit_now = True
                            break
                        if ans in ("",):
                            if cur[0] is None:
                                print("no estimate; type start,end or s")
                                continue
                            ns, ne = cur
                        elif ans.lower() == "s":
                            break
                        elif ans.lower() == "q":
                            quit_now = True
                            break
                        else:
                            mm = re.match(r"^(\d+)\s*,\s*(\d+)$", ans)
                            if mm:
                                ns, ne = int(mm.group(1)), int(mm.group(2))
                                if ns < 0 or ne > len(vn_txt) or ne <= ns:
                                    print("range out of bounds for this VN text")
                                    continue
                            else:
                                loc = find_in_vn(ans, vn_txt)
                                if loc is None:
                                    loc = find_in_vn(ans, vn_txt.lower())
                                if loc is None:
                                    print("phrase not found in VN text")
                                    continue
                                ns, ne = loc
                        id_over.setdefault(key, {})[str(n)] = [ns, ne]
                        written += 1
                        reviewed += 1
                        with open(args.overrides, "w", encoding="utf-8") as fh:
                            json.dump(overrides, fh, ensure_ascii=False, indent=1)
                        print(f"  -> set [{ns}:{ne}] {vn_txt[ns:ne]!r}")
                        break
                    if quit_now:
                        break
                if quit_now:
                    break
            if quit_now:
                break
        print(f"{base}: {file_entries} entries offered")
        if quit_now:
            break

    with open(args.overrides, "w", encoding="utf-8") as fh:
        json.dump(overrides, fh, ensure_ascii=False, indent=1)
    print(f"\nDONE: {total_entries} offered, {reviewed} answered, {written} written "
          f"-> {args.overrides}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
