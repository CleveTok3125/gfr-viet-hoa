#!/usr/bin/env python3
"""Print interp entries of one tag file with full context for manual review."""
import sys, os, re, glob
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from common import bootstrap; bootstrap()
import msgpack
from remap_tags import load_tag, build_id_text, char_map, remap_range
from extract import extract
from common import TEXT_KO, SCENARIO_KO

game = sys.argv[1]
base = sys.argv[2]
if base.startswith("text_scenario"):
    dir_rel = SCENARIO_KO; en_dir = "system/table/scenario/en"
else:
    dir_rel = TEXT_KO; en_dir = "system/table/text/en"
TAG_KEYS = ("bolds_", "colors_", "words_", "names_")

tag = load_tag(os.path.join(game, dir_rel, base + "_tag.msg"))
en_text = build_id_text(msgpack.unpackb(extract(game, os.path.join(en_dir, base + ".msg")), raw=False))
vn = msgpack.unpackb(open(os.path.join(game, dir_rel, base + ".msg"), "rb").read(), raw=False)
vn_by_id = build_id_text(vn)
en_tag = msgpack.unpackb(extract(game, os.path.join(en_dir, base + "_tag.msg")), raw=False)
en_by_id = {}
for e in en_tag["Tag"]["tags_"]:
    el = e["Element"]; en_by_id[(el.get("id_", ""), el.get("subid_", ""))] = el

idx = 0
for e in tag["Tag"]["tags_"]:
    el = e["Element"]; rid = el.get("id_", ""); sub = el.get("subid_", "")
    en_el = en_by_id.get((rid, sub)); en_t = en_text.get((rid, sub), ""); vn_t = vn_by_id.get((rid, sub), "")
    if not en_el or not en_t or not vn_t:
        continue
    m = char_map(en_t, vn_t)
    for key in TAG_KEYS:
        items = el.get(key) or []
        src = en_el.get(key) or []
        for n, item in enumerate(items):
            if n >= len(src): continue
            try:
                s = int(src[n]["Element"]["start_"]); e2 = int(src[n]["Element"]["end_"])
            except Exception:
                continue
            res = remap_range(en_t, vn_t, m, s, e2)
            meth = res[2] if res and res[0] is not None else "unresolved"
            if meth not in ("exact", "found", "marker", "match"):
                cur = (res[0], res[1]) if res and res[0] is not None else (None, None)
                est = vn_t[cur[0]:cur[1]] if cur[0] is not None else "?"
                print(f"###{idx} {rid} {key}[{n}] EN[{s}:{e2}] {meth}")
                print(f"  EN span: {en_t[s:e2]!r}")
                print(f"  EN full: {en_t}")
                print(f"  VN text: {vn_t}")
                print(f"  VN est : {est!r} at {cur}")
                print()
                idx += 1
print(f"total interp: {idx}", file=sys.stderr)
