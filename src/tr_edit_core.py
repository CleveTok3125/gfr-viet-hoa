"""Core logic for the translation editor TUI (:mod:`tr_edit`).

Pure data helpers, deliberately free of any UI dependency so they can be
unit-tested and reused by other scripts. The only external reads are the
translation / decision / override JSONs plus, when a game dir is supplied,
the English tables used to resolve row ids and speaker names.

Marker conventions (self-defined), drawn from the three authoring files
(``tag_tuning.json`` is intentionally left untouched):

    [Speaker]            read-only speaker prefix (scenario only); built from
                         data/scenario_speakers.json and dropped on parse-back
    {c:phrase}           colors_  highlight phrase   -> decisions + overrides
    {w:phrase}           words_   highlight phrase   -> decisions + overrides
    {b:phrase}           bolds_   highlight phrase   -> decisions + overrides
    {cw:phrase}          colors_+words_ on the same phrase -> both
    {p}                  zero-width player-name insertion point -> overrides

Literals ``{`` ``}`` ``[`` are escaped as ``\\{`` ``\\}`` ``\\[``.
"""
from __future__ import annotations

import json
import os
import re
import sys
import copy

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, ".."))

import msgpack  # noqa: E402

from common import bootstrap  # noqa: E402
bootstrap()

from common import (  # noqa: E402
    repo_file, load_translations, SCENARIO_KO, TEXT_KO)

HIGHLIGHT_KEYS = ("colors_", "words_", "bolds_")
HIGHLIGHT_RE = re.compile(r"\{([cbw]{1,3}):((?:[^{}]|\\.)*)\}")
PLAYER_RE = re.compile(r"\{p\}")
SPEAKER_RE = re.compile(r"^\[([^\[\]\n]*)\][ \t]*")

# key -> canonical list of tag keys written back
KEY_TAGS = {
    "c": ("colors_",),
    "w": ("words_",),
    "b": ("bolds_",),
    "cw": ("colors_", "words_"),
}

# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


class Store:
    """Handles the three authoring JSONs and, optionally, the game archive."""

    def __init__(self, game_dir=None):
        self.game = game_dir
        self.translations = load_translations()
        self.tables = self.translations.get("translations", {})
        self.decisions = self._load_json("decisions.json")
        self.overrides = self._load_json("tag_overrides.json")
        self.speakers = self._load_json("data/scenario_speakers.json")
        self._id_cache = {}
        # path -> Store index for atomic saves
        self._paths = {
            "translations.json": repo_file("translations.json"),
            "decisions.json": repo_file("decisions.json"),
            "tag_overrides.json": repo_file("tag_overrides.json"),
        }

    @staticmethod
    def _load_json(rel):
        p = os.path.join(os.path.dirname(_HERE), rel)
        if not os.path.isfile(p):
            return {}
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)

    # -- id / speaker resolution ------------------------------------------

    def reverse_id_map(self, file):
        """Return {en_text: [row_id,...]} for a table (EN source)."""
        if file in self._id_cache:
            return self._id_cache[file]
        if not self.game:
            self._id_cache[file] = {}
            return {}
        kind = "scenario" if file.startswith("text_scenario") else "text"
        rel = f"system/table/{kind}/en/{file}"
        raw = self._extract(rel)
        rev = {}
        if raw:
            try:
                rows = msgpack.unpackb(raw, raw=False)["rows_"]
            except Exception:
                rows = []
            for r in rows:
                c = r.get("column_", {})
                tx = c.get("text_", "")
                hid = c.get("id_hash_", "")
                if tx:
                    rev.setdefault(tx, []).append(hid)
        self._id_cache[file] = rev
        return rev

    def _extract(self, rel):
        if not self.game:
            return None
        try:
            from extract import extract
        except ImportError:
            return None
        return extract(self.game, rel)

    def speaker_label(self, ids):
        """Best display name for the first non-empty speaker among ids."""
        for rid in ids:
            sp = self.speakers.get(rid, {})
            for k in ("name_en", "name_ko", "chara"):
                v = sp.get(k)
                if v:
                    return v
        return None

    # -- atomic writes -----------------------------------------------------

    def save_all(self):
        self._atomic("translations.json", self.translations)
        self._atomic("decisions.json", self.decisions)
        self._atomic("tag_overrides.json", self.overrides)

    def _atomic(self, rel, data):
        p = self._paths[rel]
        # preserve each file's existing trailing-newline convention so saves
        # do not introduce spurious diffs
        has_nl = False
        if os.path.isfile(p):
            with open(p, "rb") as fh:
                fh.seek(-1, os.SEEK_END)
                has_nl = fh.read(1) == b"\n"
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
            if has_nl:
                fh.write("\n")
        os.replace(tmp, p)


# --------------------------------------------------------------------------
# Items
# --------------------------------------------------------------------------


class Item:
    """One translatable entry with its resolved identity + markers."""

    __slots__ = ("file", "en", "vn", "ids", "speaker", "markers", "player_pos")

    def __init__(self, store, file, en, vn):
        self.file = file
        self.en = en
        self.vn = vn
        rev = store.reverse_id_map(file)
        self.ids = rev.get(en, [])
        self.speaker = store.speaker_label(self.ids)
        self.markers, self.player_pos = _load_markers(
            store, file, self.ids, vn)


def iter_items(store, bases=None, holds=None):
    """Yield every item of the chosen table files.

    ``bases`` restricts to a set of table basenames; ``holds`` is an optional
    dict reused to keep one Item per (file,en) across calls.
    """
    tables = store.tables
    bases = set(bases) if bases else None
    for file, table in tables.items():
        base = file[:-len(".msg")]
        if bases is not None and base not in bases:
            continue
        for en, vn in table.items():
            key = (file, en)
            it = holds.get(key) if holds else None
            if it is None:
                it = Item(store, file, en, vn)
                if holds is not None:
                    holds[key] = it
            yield it


def search_hit(store, item, query):
    """Case-insensitive match of ``query`` against original/translation/ids."""
    q = query.lower()
    if not q:
        return True
    if q in item.en.lower() or q in item.vn.lower():
        return True
    return any(q in rid.lower() for rid in item.ids)


def matches(store, item, query):
    return search_hit(store, item, query)


# --------------------------------------------------------------------------
# Markers
# --------------------------------------------------------------------------


def _load_markers(store, file, ids, vn):
    """Merge highlight phrase markers + player position from decisions/overrides."""
    base = file[:-len(".msg")]
    player_pos = None
    groups = {}              # (vn_start, phrase) -> set(tags)
    TAG = {"colors_": "c", "words_": "w", "bolds_": "b"}
    # player name marker (zero-width insertion point)
    for rid in ids:
        ov = store.overrides.get(base, {}).get(rid, {}).get("names_")
        if ov and "0" in ov:
            player_pos = int(ov["0"][0])
    # highlight phrases: decisions give phrases, overrides give positions.
    # identical phrase at the same offset is merged into one marker (e.g. c+w).
    for rid in ids:
        dec = store.decisions.get(base, {}).get(rid, {})
        ovr = store.overrides.get(base, {}).get(rid, {})
        for key in HIGHLIGHT_KEYS:
            deco = dec.get(key, {})
            ovo = ovr.get(key, {})
            all_idx = set(map(str, deco)) | set(map(str, ovo))
            for i in sorted(all_idx, key=int):
                phrase = None
                if str(i) in deco and isinstance(deco[str(i)], list) and deco[str(i)]:
                    phrase = deco[str(i)][0]
                elif str(i) in ovo:
                    s, e = int(ovo[str(i)][0]), int(ovo[str(i)][1])
                    if 0 <= s <= e <= len(vn):
                        phrase = vn[s:e]
                if not phrase:
                    continue
                start = vn.find(phrase)
                if start < 0:
                    continue
                groups.setdefault((start, phrase), set()).add(TAG[key])
    highlights = [("".join(sorted(tags)), phrase)
                  for (start, phrase), tags in sorted(groups.items())]
    return highlights, player_pos


def _esc(s):
    return s.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _unesc(s):
    return s.replace("\\{", "{").replace("\\}", "}").replace("\\\\", "\\")


def build_compound(item, with_speaker=True):
    """Render an editable string: [Speaker] VN-with-markers.

    With ``with_speaker=False`` the speaker prefix is omitted, so callers that
    render the speaker separately (e.g. the editor header) never count it.
    """
    vn = item.vn
    edits = []
    for tag, phrase in item.markers:
        idx = vn.find(phrase)
        if idx < 0:
            continue
        edits.append((idx, idx + len(phrase), f"{{{tag}:{_esc(phrase)}}}"))
    edits.sort()
    ppos = item.player_pos
    parts = []
    cur = 0
    player_done = ppos is None
    for s, e, marker in edits:
        seg = vn[cur:s]
        seg_esc = _esc(seg)
        if not player_done and ppos is not None and cur <= ppos <= s:
            rel = min(s - cur, ppos - cur)
            parts.append(_esc(seg[:rel]) + "{p}" + _esc(seg[rel:]))
            player_done = True
        else:
            parts.append(seg_esc)
        parts.append(marker)
        cur = e
    tail = vn[cur:]
    if not player_done and ppos is not None:
        rel = min(len(tail), ppos - cur)
        parts.append(_esc(tail[:rel]) + "{p}" + _esc(tail[rel:]))
    else:
        parts.append(_esc(tail))
    body = "".join(parts)
    if item.speaker and with_speaker:
        return f"[{item.speaker}] " + body
    return body


def parse_compound(text):
    """Reverse of :func:`build_compound`.

    Returns ``(speaker, vn, highlights, player_pos)`` where ``highlights`` is
    ``[(tag, phrase), ...]`` and ``player_pos`` is an int or ``None``.
    Empty highlight phrases are dropped; id numbering is assigned fresh.
    """
    text = text.strip("\n")
    speaker = None
    m = SPEAKER_RE.match(text)
    if m:
        speaker = _unesc(m.group(1))
        text = text[m.end():]
    # extract  highlights first
    highlights = []
    out = []
    i = 0
    for mm in HIGHLIGHT_RE.finditer(text):
        out.append(text[i:mm.start()])
        tag, phrase = mm.group(1), _unesc(mm.group(2))
        key_tags = KEY_TAGS.get(tag)
        if key_tags is None:
            # unknown tag -> keep literal
            out.append(mm.group(0))
            continue
        out.append(phrase)
        rec = phrase.strip()
        if rec:
            highlights.append((tag, rec))
        i = mm.end()
    out.append(text[i:])
    body = "".join(out)
    # unescape remaining literals
    body = _unesc(body)
    player_pos = None
    pm = PLAYER_RE.search(body)
    if pm:
        player_pos = pm.start()
        body = body[:pm.start()] + body[pm.end():]
    # remove any leftover (unbalanced) literal escapes
    body = _unesc(body)
    return speaker, body, highlights, player_pos


def renumber(highlights):
    """Return {tag_key: {idx_str: [phrase]}} with fresh per-key numbering."""
    result = {k: {} for k in HIGHLIGHT_KEYS}
    counters = {k: 0 for k in HIGHLIGHT_KEYS}
    for tag, phrase in highlights:
        for k in KEY_TAGS[tag]:
            result[k][str(counters[k])] = [phrase]
            counters[k] += 1
    return result


# --------------------------------------------------------------------------
# Write-back
# --------------------------------------------------------------------------


def apply_edit(store, item, compound):
    """Persist an edited compound string to translations/decisions/overrides.

    Returns list of warning strings (non-fatal). ``item.vn`` is updated after
    a successful write.
    """
    warnings = []
    speaker, vn, highlights, player_pos = parse_compound(compound)
    base = item.file[:-len(".msg")]
    # 1. translations
    table = store.tables[item.file]
    if item.en in table:
        table[item.en] = vn
    else:
        warnings.append(f"{item.file}: EN key not found; text not saved")
    # 2. decisions (per matched rid)
    ren = renumber(highlights)
    for rid in item.ids:
        dec = store.decisions.setdefault(base, {}).setdefault(rid, {})
        for k in HIGHLIGHT_KEYS:
            if ren[k]:
                dec[k] = ren[k]
            else:
                dec.pop(k, None)
        if not dec and base in store.decisions and rid in store.decisions[base]:
            del store.decisions[base][rid]
    # 3. overrides (highlight positions + player marker)
    for rid in item.ids:
        ov = store.overrides.setdefault(base, {}).setdefault(rid, {})
        for k in HIGHLIGHT_KEYS:
            if k in ren and ren[k]:
                kmap = ov.setdefault(k, {})
                for idx, ph in ren[k].items():
                    s = vn.find(ph[0])
                    if s < 0:
                        warnings.append(
                            f"{rid} {k}[{idx}]: phrase {ph[0]!r} not found in text")
                        continue
                    kmap[idx] = [s, s + len(ph[0])]
            else:
                ov.pop(k, None)
        # names_
        if player_pos is not None:
            ov.setdefault("names_", {})["0"] = [player_pos, player_pos]
        else:
            ov.pop("names_", None)
        if not ov and base in store.overrides and rid in store.overrides[base]:
            del store.overrides[base][rid]
    if not any(v for v in store.overrides.values()):
        store.overrides = {}
    item.vn = vn
    item.speaker = speaker or item.speaker
    return warnings


# --------------------------------------------------------------------------
# Self-test
# --------------------------------------------------------------------------


def self_test(store, file, en):
    """Round-trip an item: build compound, parse it back, assert no change."""
    holds = {}
    item = next((it for it in iter_items(store, bases={file[:-len(".msg")]},
                                        holds=holds)
                 if it.en == en), None)
    if item is None:
        print(f"self-test: item not found: {en}")
        return False
    table = store.tables[file]
    before_vn = table[en]
    base = file[:-len(".msg")]
    before_dec = {r: copy.deepcopy(d)
                  for r, d in store.decisions.get(base, {}).items()}
    before_ov = {r: copy.deepcopy(d)
                 for r, d in store.overrides.get(base, {}).items()}
    compound = build_compound(item)
    speaker, vn2, hi2, pos2 = parse_compound(compound)
    warnings = apply_edit(store, item, compound)
    ok = table[en] == before_vn and not warnings
    ok = ok and all(item.vn == vn2 for _ in [0])
    # restore snapshots so self-test is non-destructive
    _restore(store, base, before_dec, before_ov)
    print(f"    compound: {compound!r}")
    print(f"    parsed vn: {vn2!r}")
    print(f"    round-trip {'OK' if ok else 'MISMATCH'}")
    if warnings:
        print(f"    warnings: {warnings}")
    return ok


def _restore(store, base, dec, ov):
    store.decisions.pop(base, None)
    store.overrides.pop(base, None)
    if dec:
        store.decisions[base] = dec
    if ov:
        store.overrides[base] = ov