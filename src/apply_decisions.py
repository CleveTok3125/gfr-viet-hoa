#!/usr/bin/env python3
"""Apply manual highlight decisions (VN phrase per entry) to tag_overrides.json.

highlight_decisions.json format: (internal name stays `decisions`)
    { file_base: { rid: { tag_key: { item_idx: ["vn phrase", occurrence] } } } }

(Stored on disk as `highlight_decisions.json`; internal name stays `decisions`.)

occurrence is optional (default 0 = first match). If the phrase is not found
in the VN text, the entry is skipped and reported.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import msgpack

from common import SCENARIO_KO, TEXT_KO, bootstrap

bootstrap()
from remap_tags import build_id_text, load_tag

game = sys.argv[1]
decisions_path = sys.argv[2]
out_path = sys.argv[3] if len(sys.argv) > 3 else "tag_overrides.json"

with open(decisions_path, "r", encoding="utf-8") as fh:
    decisions = json.load(fh)

out = {}
if os.path.exists(out_path):
    with open(out_path, "r", encoding="utf-8") as fh:
        out = json.load(fh)

def vn_by_id_for(base):
    if base.startswith("text_scenario"):
        dir_rel = SCENARIO_KO
    else:
        dir_rel = TEXT_KO
    vn_path = os.path.join(game, dir_rel, base + ".msg")
    with open(vn_path, "rb") as fh:
        vn = msgpack.unpackb(fh.read(), raw=False)
    return build_id_text(vn), dir_rel

def subids_for(base):
    """Return {id: [subid,...]} from the tag file."""
    if base.startswith("text_scenario"):
        dir_rel = SCENARIO_KO
    else:
        dir_rel = TEXT_KO
    tag = load_tag(os.path.join(game, dir_rel, base + "_tag.msg"))
    out = {}
    for e in tag["Tag"]["tags_"]:
        el = e["Element"]
        out.setdefault(el.get("id_", ""), []).append(el.get("subid_", ""))
    return out

missed = 0
applied = 0

def flat_to_real(text, target_flat):
    """Map an index in the whitespace-collapsed text back to a real index."""
    flat_idx = 0
    real = 0
    while real < len(text) and flat_idx < target_flat:
        c = text[real]
        if re.match(r"\s", c):
            if flat_idx == 0 or not re.match(r"\s", text[real - 1]):
                flat_idx += 1
        else:
            flat_idx += 1
        real += 1
    return real

def find_normalized(text, phrase, occ):
    """Locate phrase in text ignoring newline-vs-space differences."""
    flat_text = re.sub(r"\s+", " ", text)
    flat_phrase = re.sub(r"\s+", " ", phrase)
    start = 0
    found_flat = -1
    for _ in range(occ + 1):
        found_flat = flat_text.find(flat_phrase, start)
        if found_flat < 0:
            return -1, -1, 0
        start = found_flat + len(flat_phrase)
    return found_flat, flat_to_real(text, found_flat), flat_to_real(text, found_flat + len(flat_phrase))

for base, rid_map in decisions.items():
    vn_by_id, _ = vn_by_id_for(base)
    subs = subids_for(base)
    for rid, key_map in rid_map.items():
        vn_t = ""
        sub_list = subs.get(rid, [""])
        for sub in sub_list:
            vn_t = vn_by_id.get((rid, sub), "")
            if vn_t:
                break
        if not vn_t:
            print(f"SKIP {base} {rid}: no VN text")
            missed += 1
            continue
        for key, idx_map in key_map.items():
            for idx, spec in idx_map.items():
                phrase = spec[0]
                occ = spec[1] if isinstance(spec, list) and len(spec) > 1 else 0
                found, real_start, real_end = find_normalized(vn_t, phrase, occ)
                if found < 0:
                    print(f"SKIP {base} {rid} {key}[{idx}]: phrase {phrase!r} not in VN text")
                    missed += 1
                    continue
                file_over = out.setdefault(base, {})
                id_over = file_over.setdefault(rid, {})
                id_over.setdefault(key, {})[str(idx)] = [real_start, real_end]
                applied += 1

with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1)
print(f"applied {applied}, missed {missed} -> {out_path}")
