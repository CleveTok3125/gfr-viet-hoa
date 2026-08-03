#!/usr/bin/env python3
"""Remap *_tag.msg highlight ranges to match the translated (VN) text.

The game stores bold/color/word/name ranges as char indices computed
against the original EN text. Since the translated text has different
lengths, those indices no longer align. This script re-finds each
highlighted substring inside the VN text and rewrites start_/end_.

Run from repo root:
    python3 -m src.remap_tags --game <dir> --file text_scenario_730 [--write]
"""
import argparse
import difflib
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, ".."))

from common import bootstrap  # noqa: E402
bootstrap()
import msgpack  # noqa: E402

from extract import extract  # noqa: E402
from common import TEXT_KO, SCENARIO_KO  # noqa: E402

WHITESPACE_RE = re.compile(r"\s+")
WORD_RE = re.compile(r"\S+")

TAG_KEYS = ("bolds_", "colors_", "words_", "names_")


def load_tag(path):
    with open(path, "rb") as fh:
        return msgpack.unpackb(fh.read(), raw=False)


def save_tag(path, data):
    # pack first, then write (avoid zero-byte files on failure)
    blob = msgpack.packb(data)
    with open(path, "wb") as fh:
        fh.write(blob)


def text_rows(blob):
    for r in blob["rows_"]:
        yield r["column_"]


def build_id_text(blob):
    """Map (id_hash_, subid_hash_) -> text_ ."""
    out = {}
    for r in blob["rows_"]:
        c = r["column_"]
        out[(c.get("id_hash_", ""), c.get("subid_hash_", ""))] = c.get("text_", "")
    return out


def char_map(en_text, vn_text):
    """Build EN->VN char index map using difflib opcodes.

    Returns a dict en_idx -> vn_idx for aligned ('equal') regions.
    """
    sm = difflib.SequenceMatcher(None, en_text, vn_text, autojunk=False)
    mapping = {}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                mapping[i1 + k] = j1 + k
    return mapping


def find_in_vn(sub, vn_text):
    """Locate `sub` in vn_text; returns (start, end) or None."""
    if not sub:
        return None
    idx = vn_text.find(sub)
    if idx != -1:
        return idx, idx + len(sub)
    # fuzzy: collapse all whitespace
    sub_n = WHITESPACE_RE.sub(" ", sub).strip()
    vn_n = WHITESPACE_RE.sub(" ", vn_text)
    idx = vn_n.find(sub_n)
    if idx != -1:
        # map back to real string indices is non-trivial after collapse;
        # require unique-ish match and accept approximate index
        return idx, idx + len(sub_n)
    return None


def remap_range(en_text, vn_text, mapping, start, end):
    """Given EN [start,end), return new (start,end) for VN or None."""
    length = end - start
    if length == 0:
        # zero-length marker (e.g. player-name insertion point):
        # keep proportional position
        if not en_text:
            return None
        est = round(start * len(vn_text) / len(en_text))
        est = max(0, min(len(vn_text), est))
        return est, est
    if length < 0:
        return None
    # 1) whole span covered by char map (exact alignment)
    keys = [start + k for k in range(length)]
    if all(k in mapping for k in keys):
        vals = [mapping[k] for k in keys]
        if vals == sorted(vals) and (vals[-1] - vals[0] + 1) == len(vals):
            return vals[0], vals[-1] + 1
    # 2) locate the exact substring in VN
    sub = en_text[start:end]
    found = find_in_vn(sub, vn_text)
    if found:
        return found
    # 3) interpolate using nearest aligned anchors around the span
    est = _interpolate(en_text, vn_text, mapping, start, end)
    if est:
        return _snap_words(vn_text, *est)
    return None


def _snap_words(vn_text, s, e):
    """Snap (s,e) to nearest word boundaries so the highlight never cuts a
    word in half."""
    if not vn_text:
        return s, e
    # expand start leftwards to previous space (or line start)
    ns = s
    while ns > 0 and not vn_text[ns - 1].isspace():
        ns -= 1
    # expand end rightwards to next space (or line end)
    ne = e
    while ne < len(vn_text) and not vn_text[ne].isspace():
        ne += 1
    # do not cross a newline while snapping
    for i in range(s - 1, max(s - 60, -1), -1):
        if vn_text[i] == "\n":
            ns = max(ns, i + 1)
            break
    for i in range(e, min(e + 60, len(vn_text))):
        if vn_text[i] == "\n":
            ne = min(ne, i)
            break
    if ne <= ns:
        ne = ns + 1
    ns = max(0, min(ns, len(vn_text)))
    ne = max(ns, min(ne, len(vn_text)))
    return ns, ne


def _interpolate(en_text, vn_text, mapping, start, end):
    """Estimate VN span via aligned anchors, interpolating within lines.

    The VN text is re-aligned to the EN line structure (same number of
    lines), so we first locate which EN line the span falls in and confine
    the interpolation to the matching VN line. This gives far better
    accuracy than whole-sentence ratio interpolation.
    Returns (start, end) or None if no anchors exist at all.
    """
    if not en_text or not vn_text:
        return None
    en_lines = en_text.split("\n")
    vn_lines = vn_text.split("\n")
    if not mapping and len(en_lines) == len(vn_lines):
        # line-confined pure ratio
        idx = _line_of(en_text, start)
        if idx is not None and idx < len(vn_lines):
            e_start = 0 if idx == 0 else sum(len(l) + 1 for l in en_lines[:idx])
            v_start = 0 if idx == 0 else sum(len(l) + 1 for l in vn_lines[:idx])
            en_len = len(en_lines[idx])
            vn_len = len(vn_lines[idx])
            if en_len > 0:
                r = vn_len / en_len
                s = v_start + round((start - e_start) * r)
                e = v_start + round((end - e_start) * r)
                s = max(v_start, min(v_start + vn_len, s))
                e = max(s + 1, min(v_start + vn_len, e))
                return s, e
        r = len(vn_text) / len(en_text)
        s = max(0, min(len(vn_text), round(start * r)))
        e = max(s + 1, min(len(vn_text), round(end * r)))
        return s, e
    anchors = sorted(mapping.items())  # (en_idx, vn_idx)
    lo, hi = None, None
    for en_i, vn_i in anchors:
        if en_i <= start:
            lo = (en_i, vn_i)
        if en_i >= end:
            hi = (en_i, vn_i)
            break
    if lo is None and hi is None:
        # anchors only exist inside the span; line-confined ratio fallback
        if len(en_lines) == len(vn_lines):
            idx = _line_of(en_text, start)
            if idx is not None and idx < len(vn_lines):
                e_start = 0 if idx == 0 else sum(len(l) + 1 for l in en_lines[:idx])
                v_start = 0 if idx == 0 else sum(len(l) + 1 for l in vn_lines[:idx])
                en_len = len(en_lines[idx])
                vn_len = len(vn_lines[idx])
                if en_len > 0:
                    r = vn_len / en_len
                    s = max(v_start, min(v_start + vn_len, v_start + round((start - e_start) * r)))
                    e = max(s + 1, min(v_start + vn_len, v_start + round((end - e_start) * r)))
                    return s, e
        r = len(vn_text) / len(en_text)
        s = max(0, min(len(vn_text), round(start * r)))
        e = max(s + 1, min(len(vn_text), round(end * r)))
        return s, e
    if lo is None:
        # only right anchor: extrapolate backwards using per-char ratio
        en_i, vn_i = hi
        ratio = vn_i / en_i if en_i else (len(vn_text) / len(en_text))
        s = max(0, round(start * ratio))
        e = min(len(vn_text), round(end * ratio))
        return s, max(s + 1, e)
    if hi is None:
        en_i, vn_i = lo
        ratio = ((len(vn_text) - vn_i) / (len(en_text) - en_i)
                 if (len(en_text) - en_i) > 0 else 1.0)
        s = max(0, min(len(vn_text), round(vn_i + (start - en_i) * ratio)))
        e = max(s + 1, min(len(vn_text), round(vn_i + (end - en_i) * ratio)))
        return s, e
    # interpolate linearly between lo and hi
    lo_en, lo_vn = lo
    hi_en, hi_vn = hi
    span = hi_en - lo_en
    if span <= 0:
        return None
    s = round(lo_vn + (start - lo_en) * (hi_vn - lo_vn) / span)
    e = round(lo_vn + (end - lo_en) * (hi_vn - lo_vn) / span)
    s = max(0, min(len(vn_text), s))
    e = max(s + 1, min(len(vn_text), e))
    return s, e


def _line_of(text, pos):
    """Return the 0-based line index containing `pos`, or None."""
    offset = 0
    for i, line in enumerate(text.split("\n")):
        if offset <= pos < offset + len(line) + 1:
            return i
        offset += len(line) + 1
    return None


def remap_tag_file(game_dir, rel_text, rel_tag, tag_blob, en_text, vn_text,
                   en_tag_blob, dry_run, verbose):
    """Rewrite ranges in tag_blob using EN tag indices as the source of truth.

    The ko tag on disk and the EN tag in the archive share the same ranges
    (indices are computed against the EN text). We therefore read ranges
    from the immutable EN tag, remap them to the VN text, and write back to
    the ko file, preserving the ko file's string-valued format.
    Returns (changed, rows, unfound).
    """
    vn_by_id = build_id_text(vn_text)

    def norm(blob):
        out = {}
        for entry in blob["Tag"]["tags_"]:
            el = entry["Element"]
            out[(el.get("id_", ""), el.get("subid_", ""))] = el
        return out

    en_by_id = norm(en_tag_blob) if en_tag_blob else {}

    changed = 0
    rows = 0
    unfound = 0
    skipped = 0
    for entry in tag_blob["Tag"]["tags_"]:
        el = entry["Element"]
        rid = el.get("id_", "")
        subid = el.get("subid_", "")
        en_el = en_by_id.get((rid, subid))
        vn_txt = vn_by_id.get((rid, subid), "")
        if not vn_txt:
            continue
        if en_el is None:
            # no EN ground truth -> leave this entry untouched
            skipped += 1
            continue
        en_txt = en_text.get((rid, subid), "") if en_text else ""
        if not en_txt:
            skipped += 1
            continue
        m = char_map(en_txt, vn_txt)
        for key in TAG_KEYS:
            items = el.get(key)
            if not items:
                continue
            src_items = en_el.get(key, [])
            for n, item in enumerate(items):
                elem = item["Element"]
                if n >= len(src_items):
                    # ko tag has more ranges than EN tag; no ground truth,
                    # leave this range untouched to stay idempotent
                    continue
                try:
                    start = int(src_items[n]["Element"]["start_"])
                    end = int(src_items[n]["Element"]["end_"])
                except (KeyError, ValueError, TypeError):
                    continue
                rows += 1
                sub_en = en_txt[start:end]
                new = remap_range(en_txt, vn_txt, m, start, end)
                if new is None:
                    unfound += 1
                    if verbose:
                        print(f"  UNFOUND {rid} {key} [{start}:{end}] {sub_en!r}")
                    continue
                ns, ne = new
                if ns != start or ne != end:
                    elem["start_"] = str(ns)
                    elem["end_"] = str(ne)
                    changed += 1
                    if verbose:
                        print(f"  {rid} {key} [{start}:{end}] -> [{ns}:{ne}] {sub_en!r}")
    return changed, rows, unfound, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True, help="game directory")
    ap.add_argument("--file", help="table basename, e.g. text_scenario_730")
    ap.add_argument("--all", action="store_true",
                    help="process every *_tag.msg in text/ko and scenario/ko")
    ap.add_argument("--write", action="store_true", help="write changes back")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    game = args.game
    if not (args.file or args.all):
        ap.error("provide --file or --all")

    if args.file:
        bases = [args.file]
    else:
        import glob
        bases = []
        for d in (TEXT_KO, SCENARIO_KO):
            for p in sorted(glob.glob(os.path.join(game, d, "*_tag.msg"))):
                b = os.path.basename(p)
                if b.endswith("_tag.msg"):
                    bases.append(b[: -len("_tag.msg")])
        bases = sorted(set(bases))

    total_changed = total_rows = total_unfound = total_skipped = 0
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

        en_tag_path = os.path.join(en_dir, base + "_tag.msg")
        en_tag_bytes = extract(game, en_tag_path)
        en_tag_blob = msgpack.unpackb(en_tag_bytes, raw=False) if en_tag_bytes else None

        vn_path = os.path.join(game, dir_rel, base + ".msg")
        if not os.path.exists(vn_path):
            continue
        vn_text = msgpack.unpackb(open(vn_path, "rb").read(), raw=False)

        changed, rows, unfound, skipped = remap_tag_file(
            game, dir_rel, ko_tag_path, tag_blob, en_text, vn_text,
            en_tag_blob, args.write, args.verbose)
        total_changed += changed
        total_rows += rows
        total_unfound += unfound
        total_skipped += skipped

        if args.write and changed:
            save_tag(ko_tag_path, tag_blob)
        if args.file or args.verbose or (args.all and (changed or unfound)):
            print(f"{base}: ranges={rows} changed={changed} unfound={unfound}"
                  + (" written" if (args.write and changed) else ""))

    print(f"\nTOTAL: files={len(bases)} ranges={total_rows} changed={total_changed} unfound={total_unfound} skipped={total_skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
