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

from common import bootstrap

bootstrap()
import msgpack

from common import SCENARIO_KO, TEXT_KO
from extract import extract

WHITESPACE_RE = re.compile(r"\s+")
WORD_RE = re.compile(r"\S+")
PLACEHOLDER_RE = re.compile(r"\{[^}]*\}")

TAG_KEYS = ("bolds_", "colors_", "words_", "names_")


def _expanded_width(tok):
    """Expanded string width of a placeholder token in tag space."""
    return 7 if tok == "{:s}" else 6


def _scan_expanded(text):
    """Scan expanded-space positions of <d> markers and placeholders.

    Returns (d_exp, d_raw, ph_start, ph_end, ph_raw_end):
      d_exp       expanded start of each <d>
      d_raw       raw start of each <d>
      ph_start    {placeholder idx: expanded start}
      ph_end      {placeholder idx: expanded end}
      ph_raw_end  {placeholder idx: raw end}
    """
    d_exp = []
    d_raw = []
    ph_start = {}
    ph_end = {}
    ph_raw_end = {}
    i = 0
    ex = 0
    pidx = 0
    while i < len(text):
        if text.startswith("<d>", i):
            d_exp.append(ex)
            d_raw.append(i)
            ex += 3
            i += 3
        elif text[i] == "{":
            m = PLACEHOLDER_RE.match(text, i)
            w = _expanded_width(m.group())
            ph_start[pidx] = ex
            ph_end[pidx] = ex + w
            ph_raw_end[pidx] = i + len(m.group())
            ex += w
            i = m.end()
            pidx += 1
        else:
            ex += 1
            i += 1
    return d_exp, d_raw, ph_start, ph_end, ph_raw_end


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def remap_formats(vn_text, items):
    """Rewrite formats_ start_/end_ to the VN placeholder positions.

    formats_[i] is a zero-length marker at the expanded position right
    after placeholder `index_`. Returns the number of changed entries.
    """
    if not items:
        return 0
    _, _, _, ph_end, _ = _scan_expanded(vn_text)
    changed = 0
    for item in items:
        el = item.get("Element")
        if not el:
            continue
        ix = _as_int(el.get("index_"))
        e = ph_end.get(ix) if ix is not None else None
        if e is None:
            continue
        s = str(e)
        if el.get("start_") != s or el.get("end_") != s:
            el["start_"] = s
            el["end_"] = s
            changed += 1
    return changed


def remap_dynamics(vn_text, colors, items):
    """Rewrite dynamics_ start_ to VN positions per dtag.

    dtag semantics (validated against the EN/KO ground truth):
      24   expanded start of the k-th <d> in order of appearance
      28   expanded start of the <d> right before placeholder `index_`
      29   expanded start of the <d> right after  placeholder `index_`
      16   colors_[index_].start_ (raw color region open)
      17   raw position after the <d> closing color region `index_`
      4/26 raw position of the <d> right after placeholder `index_`
    Returns the number of changed entries.
    """
    if not items:
        return 0
    d_exp, d_raw, ph_start, ph_end, ph_raw_end = _scan_expanded(vn_text)
    changed = 0
    d24 = 0
    for item in items:
        el = item.get("Element")
        if not el:
            continue
        dt = _as_int(el.get("dtag_"))
        ix = _as_int(el.get("index_"))
        nv = None
        if dt == 24:
            if d24 < len(d_exp):
                nv = d_exp[d24]
            d24 += 1
        elif dt == 28 and ix is not None:
            p = ph_start.get(ix)
            if p is not None and p >= 3:
                nv = p - 3
        elif dt == 29 and ix is not None:
            p = ph_end.get(ix)
            if p is not None:
                nv = p
        elif dt in (4, 26) and ix is not None:
            p = ph_raw_end.get(ix)
            if p is not None:
                nv = p
        elif dt == 16 and ix is not None and 0 <= ix < len(colors):
            nv = _as_int(colors[ix].get("Element", {}).get("start_"))
        elif dt == 17 and ix is not None and 0 <= ix < len(colors):
            cs = _as_int(colors[ix].get("Element", {}).get("start_"))
            if cs is not None:
                cands = [r for r in d_raw if r > cs]
                if cands:
                    nv = cands[0] + 3
        if nv is not None and el.get("start_") != str(nv):
            el["start_"] = str(nv)
            changed += 1
    return changed


def remap_times(vn_text, items, en_text=None, mapping=None):
    """Rewrite times_ start_/end_ to VN text positions.

    times_ entries carry the text-reveal / voice-sync pacing: each marker holds
    ``time_`` (seconds), ``wait_`` (wait flag) and the character offset
    (``start_`` == ``end_``) in the string where the engine pauses the text to
    stay in sync with the voice line. The offsets are computed against the
    original (EN) text, so once the string is translated they no longer point
    at the right character. We remap each marker's offset from the EN text to
    the VN text via the EN->VN char map (anchor interpolation), keeping the
    ``time_``/``wait_`` values untouched. Returns the number of changed
    entries.
    """
    if not items or not en_text or not vn_text:
        return 0
    m = mapping if mapping is not None else char_map(en_text, vn_text)
    changed = 0
    for item in items:
        el = item.get("Element")
        if not el:
            continue
        try:
            start = int(el["start_"])
            end = int(el["end_"])
        except (KeyError, ValueError, TypeError):
            continue
        # zero-length marker -> remap the single position
        est = _interpolate(en_text, vn_text, m, start, end)
        if est is None:
            # no aligned anchors: fall back to a proportional estimate
            if len(en_text) == 0:
                continue
            ratio = len(vn_text) / len(en_text)
            est = (round(start * ratio), round(end * ratio))
        ns, ne = est
        ns = max(0, min(len(vn_text), ns))
        ne = max(ns, min(len(vn_text), ne))
        if start == end:
            # keep point markers as points (game expects start_ == end_)
            pos = round((ns + ne) / 2)
            ns = ne = max(0, min(len(vn_text), pos))
        if el.get("start_") != str(ns) or el.get("end_") != str(ne):
            el["start_"] = str(ns)
            el["end_"] = str(ne)
            changed += 1
    return changed


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


def best_match(sub, vn_text):
    """Find the closest (start, end) of `sub` inside vn_text.

    Uses difflib matching blocks so it survives light rewording (word order,
    inline punctuation) that a plain substring search would miss. Returns
    (start, end, ratio) or None if nothing remotely close exists.
    """
    if not sub or not vn_text:
        return None
    sm = difflib.SequenceMatcher(None, sub, vn_text, autojunk=False)
    best = None
    for b in sm.get_matching_blocks():
        if b.size == 0:
            continue
        ratio = b.size / len(sub)
        if best is None or b.size > best[2] or (
                b.size == best[2] and ratio > best[3]):
            best = (b.b, b.b + b.size, b.size, ratio)
    if best is None:
        return None
    return best[0], best[1], best[3]


def _word_tokens(text):
    """Split a highlighted span into significant word tokens."""
    return [w for w in WORD_RE.findall(text) if len(w) >= 3]


def remap_range(en_text, vn_text, mapping, start, end):
    """Given EN [start,end), return (new_start, new_end, method) for VN.

    method is one of:
      'marker'    zero-length marker, position estimated proportionally
      'exact'     whole span aligned by the char map
      'found'     substring located literally in VN
      'match'     closest difflib block found in VN (ratio-based)
      'interp'    line/anchor interpolation fallback
      'unresolved' nothing usable found -> needs a manual override
    """
    length = end - start
    if length == 0:
        # zero-length marker (e.g. player-name insertion point):
        # keep proportional position
        if not en_text:
            return None, None, 'unresolved'
        est = round(start * len(vn_text) / len(en_text))
        est = max(0, min(len(vn_text), est))
        return est, est, 'marker'
    if length < 0:
        return None, None, 'unresolved'
    # 1) whole span covered by char map (exact alignment)
    keys = [start + k for k in range(length)]
    if all(k in mapping for k in keys):
        vals = [mapping[k] for k in keys]
        if vals == sorted(vals) and (vals[-1] - vals[0] + 1) == len(vals):
            return vals[0], vals[-1] + 1, 'exact'
    # 2) locate the exact substring in VN
    sub = en_text[start:end]
    found = find_in_vn(sub, vn_text)
    if found:
        return found[0], found[1], 'found'
    # 2.2) case-insensitive literal match (proper nouns kept verbatim)
    lc_vn = vn_text.lower()
    m2 = best_match(sub.lower(), lc_vn)
    if m2 and m2[2] >= 0.9 and len(sub) >= 4:
        s, e, ratio = m2
        ns, ne = _snap_words(vn_text, s, e)
        return ns, ne, 'match'
    # 2.3) re-find via significant word tokens (proper nouns inside the span)
    toks = _word_tokens(sub)
    if toks:
        vn_lower = vn_text.lower()
        hits = []
        for tok in toks:
            idx = vn_lower.find(tok.lower())
            if idx != -1:
                hits.append((idx, tok))
        if hits:
            hits.sort()
            best = None
            for i, (idx, tok) in enumerate(hits):
                span_s = idx
                span_e = idx + len(tok)
                j = i
                while j + 1 < len(hits) and hits[j + 1][0] - span_e < 12:
                    j += 1
                    span_e = max(span_e, hits[j][0] + len(hits[j][1]))
                if best is None or (span_e - span_s) > (best[1] - best[0]):
                    best = (span_s, span_e)
            ns, ne = _snap_words(vn_text, *best)
            return ns, ne, 'match'
    # 2.5) locate the closest block of the span in VN
    matched = best_match(sub, vn_text)
    if matched and matched[2] >= 0.5:
        s, e, ratio = matched
        ns, ne = _snap_words(vn_text, s, e)
        if ratio >= 0.8:
            return ns, ne, 'match'
        return ns, ne, 'interp'
    # 3) interpolate using nearest aligned anchors around the span
    est = _interpolate(en_text, vn_text, mapping, start, end)
    if est:
        return _snap_words(vn_text, *est) + ('interp',)
    return None, None, 'unresolved'


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
                   en_tag_blob, dry_run, verbose, overrides=None, report=None):
    """Rewrite ranges in tag_blob using EN tag indices as the source of truth.

    The ko tag on disk and the EN tag in the archive share the same ranges
    (indices are computed against the EN text). We therefore read ranges
    from the immutable EN tag, remap them to the VN text, and write back to
    the ko file, preserving the ko file's string-valued format.

    `overrides` is a dict {file_base: {id: {tag_key: {item_idx: [start, end]}}}}
    giving exact VN character ranges supplied by a human; any range with an
    override is used verbatim and reported as 'manual'.

    `report`, if given, is a list that receives one dict per range that was
    NOT resolved exactly (everything needing a human check).

    Returns (changed, rows, unfound, skipped, manual).
    """
    vn_by_id = build_id_text(vn_text)

    def norm(blob):
        out = {}
        for entry in blob["Tag"]["tags_"]:
            el = entry["Element"]
            out[(el.get("id_", ""), el.get("subid_", ""))] = el
        return out

    en_by_id = norm(en_tag_blob) if en_tag_blob else {}

    file_over = (overrides or {}).get(rel_tag.split("/")[-1][: -len("_tag.msg")], {})
    changed = 0
    rows = 0
    unfound = 0
    skipped = 0
    manual = 0
    for entry in tag_blob["Tag"]["tags_"]:
        el = entry["Element"]
        rid = el.get("id_", "")
        subid = el.get("subid_", "")
        en_el = en_by_id.get((rid, subid))
        vn_txt = vn_by_id.get((rid, subid), "")
        if not vn_txt:
            continue
        # dynamics_/formats_ are positional markers (no EN/ko range pairing like
        # the span keys below). Recompute them purely from the VN text so they
        # point at the right <d>/placeholder offsets in the translated string.
        # This is text-driven and independent of EN ground truth, so it runs
        # for KO-only rows too.
        if el.get("formats_"):
            changed += remap_formats(vn_txt, el["formats_"])
        if el.get("dynamics_"):
            colors = el.get("colors_") or []
            changed += remap_dynamics(vn_txt, colors, el["dynamics_"])
        if el.get("times_") and en_el is not None:
            # voice/text sync markers: offsets index the EN string, so remap
            # them to the VN text using the EN tag as ground truth.
            en_times = en_el.get("times_")
            if en_times:
                src_txt = en_text.get((rid, subid), "") if en_text else ""
                if src_txt:
                    m0 = char_map(src_txt, vn_txt)
                    changed += remap_times(vn_txt, el["times_"],
                                           src_txt, m0)
        if en_el is None:
            # no EN ground truth -> span ranges left untouched
            skipped += 1
            continue
        en_txt = en_text.get((rid, subid), "") if en_text else ""
        if not en_txt:
            skipped += 1
            continue
        m = char_map(en_txt, vn_txt)
        id_over = file_over.get(rid, {})
        for key in TAG_KEYS:
            items = el.get(key)
            if not items:
                continue
            src_items = en_el.get(key, [])
            for n, item in enumerate(items):
                elem = item["Element"]
                override = id_over.get(key, {}).get(str(n))
                if n >= len(src_items):
                    # ko tag has more ranges than EN tag. Without a manual
                    # override there is no ground truth, so leave the range
                    # untouched to stay idempotent. A manual override extends
                    # the tag set (e.g. an added player-name placeholder)
                    # and is applied verbatim.
                    if override:
                        ns, ne = int(override[0]), int(override[1])
                        elem["start_"] = str(ns)
                        elem["end_"] = str(ne)
                        changed += 1
                    continue
                try:
                    start = int(src_items[n]["Element"]["start_"])
                    end = int(src_items[n]["Element"]["end_"])
                except (KeyError, ValueError, TypeError):
                    continue
                rows += 1
                sub_en = en_txt[start:end]
                override = id_over.get(key, {}).get(str(n))
                if override:
                    ns, ne = int(override[0]), int(override[1])
                    method = "manual"
                else:
                    new = remap_range(en_txt, vn_txt, m, start, end)
                    if new is None or new[0] is None:
                        unfound += 1
                        if verbose:
                            print(f"  UNFOUND {rid} {key} [{start}:{end}] {sub_en!r}")
                        if report is not None:
                            report.append({
                                "file": rel_tag.split("/")[-1], "id": rid,
                                "key": key, "item": n, "en_start": start, "en_end": end,
                                "en_text": sub_en, "vn_text": vn_txt, "en_full": en_txt,
                                "method": "unresolved",
                            })
                        continue
                    ns, ne, method = new
                    if report is not None and method not in ("exact", "found", "marker", "match"):
                        report.append({
                            "file": rel_tag.split("/")[-1], "id": rid,
                            "key": key, "item": n, "en_start": start, "en_end": end,
                            "en_text": sub_en, "vn_text": vn_txt, "en_full": en_txt,
                            "vn_start": ns, "vn_end": ne, "method": method,
                        })
                if method == "manual":
                    manual += 1
                if ns != start or ne != end:
                    elem["start_"] = str(ns)
                    elem["end_"] = str(ne)
                    changed += 1
                    if verbose:
                        print(f"  {rid} {key} [{start}:{end}] -> [{ns}:{ne}] {sub_en!r}")
    return changed, rows, unfound, skipped, manual


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True, help="game directory")
    ap.add_argument("--file", help="table basename, e.g. text_scenario_730")
    ap.add_argument("--all", action="store_true",
                    help="process every *_tag.msg in text/ko and scenario/ko")
    ap.add_argument("--write", action="store_true", help="write changes back")
    ap.add_argument("--fix-sizes", action="store_true",
                    help="after --write, update ExternalFileSizes in data.i "
                         "for every changed tag file")
    ap.add_argument("--overrides", default=None,
                    help="JSON file of manual VN ranges (tag_overrides.json)")
    ap.add_argument("--report", default=None,
                    help="write a JSON report of ranges needing review")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    game = args.game
    if not (args.file or args.all):
        ap.error("provide --file or --all")

    overrides = {}
    if args.overrides:
        import jsonio as json
        with open(args.overrides, "r", encoding="utf-8") as fh:
            overrides = json.load(fh)
        print(f"loaded {len(overrides)} override file(s) from {args.overrides}")

    report = [] if args.report else None

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
    total_manual = 0
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
        with open(vn_path, "rb") as fh:
            vn_text = msgpack.unpackb(fh.read(), raw=False)

        changed, rows, unfound, skipped, manual = remap_tag_file(
            game, dir_rel, ko_tag_path, tag_blob, en_text, vn_text,
            en_tag_blob, args.write, args.verbose, overrides, report)
        total_changed += changed
        total_rows += rows
        total_unfound += unfound
        total_skipped += skipped
        total_manual += manual

        if args.write and changed:
            save_tag(ko_tag_path, tag_blob)
        if args.file or args.verbose or (args.all and (changed or unfound)):
            print(f"{base}: ranges={rows} changed={changed} unfound={unfound}"
                  + (" written" if (args.write and changed) else ""))

    if args.report:
        import jsonio as json
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print(f"wrote {len(report)} review entries to {args.report}")

    if args.write and args.fix_sizes:
        # The game validates the declared ExternalFileSizes of loose tag
        # files against disk. Rewriting a tag table changes its size, so we
        # must update the declared size in data.i or the engine ignores the
        # patched tag and renders literal <d> markers.
        from datai import fix_sizes
        rels = []
        for base in bases:
            if base.startswith("text_scenario"):
                rel = os.path.join("system/table/scenario/ko", base + "_tag.msg")
            else:
                rel = os.path.join("system/table/text/ko", base + "_tag.msg")
            if os.path.exists(os.path.join(game, "data", rel)):
                rels.append(rel)
        fixes = fix_sizes(game, os.path.join(game, "data.i"), rels)
        print(f"fixed {len(fixes)} ExternalFileSizes for tag files in data.i")

    print(f"\nTOTAL: files={len(bases)} ranges={total_rows} changed={total_changed}"
          + f" unfound={total_unfound} skipped={total_skipped} manual={total_manual}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
