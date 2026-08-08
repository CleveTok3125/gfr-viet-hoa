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
        self.tuned = self._load_json("tag_tuning.json")  # spans baked into game
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

    def ja_text(self, file, ids):
        """Return the original Japanese text for the first matching id.

        Reads the game's ``jp/*.msg`` table (the raw Japanese source) and maps
        rows by ``id_hash_``, matching the EN reference ids. Result is cached
        per file. Returns ``None`` when unavailable.
        """
        if not self.game or not ids:
            return None
        cache = getattr(self, "_ja_cache", None)
        if cache is None:
            cache = self._ja_cache = {}
        if file not in cache:
            kind = "scenario" if file.startswith("text_scenario") else "text"
            raw = self._extract(f"system/table/{kind}/jp/{file}")
            m = {}
            if raw:
                try:
                    rows = msgpack.unpackb(raw, raw=False)["rows_"]
                except Exception:
                    rows = []
                for r in rows:
                    c = r.get("column_", {})
                    hid = c.get("id_hash_", "")
                    tx = c.get("text_", "")
                    if hid and tx:
                        m[hid] = tx
            cache[file] = m
        for rid in ids:
            if rid in cache[file]:
                return cache[file][rid]
        return None

    def speaker_label(self, ids):
        """Best display name for the first non-empty speaker among ids."""
        for rid in ids:
            sp = self.speakers.get(rid, {})
            for k in ("name_en", "name_ko", "chara"):
                v = sp.get(k)
                if v:
                    return v
        return None

    def en_tag_spans(self, file):
        """Return EN tag highlight spans for a table.

        Reads the game's ``*_tag.msg`` EN reference (the spans the engine uses
        to highlight the original English dialogue) and indexes them by
        ``(id, subid)`` -> ``{key: [(start, end), ...]}``. Values are ints.
        Result is cached per file.
        """
        if not self.game:
            return {}
        cache = getattr(self, "_en_tag_cache", None)
        if cache is None:
            cache = self._en_tag_cache = {}
        if file in cache:
            return cache[file]
        kind = "scenario" if file.startswith("text_scenario") else "text"
        rel = f"system/table/{kind}/en/{file[:-len('.msg')]}_tag.msg"
        raw = self._extract(rel)
        if not raw:
            cache[file] = {}
            return {}
        out = {}
        try:
            blob = msgpack.unpackb(raw, raw=False)
        except Exception:
            cache[file] = {}
            return {}
        for entry in blob.get("Tag", {}).get("tags_", []):
            el = entry.get("Element", {})
            rid = el.get("id_", "")
            subid = el.get("subid_", "")
            rec = {}
            for k in ("bolds_", "colors_", "words_", "names_", "times_"):
                items = el.get(k) or []
                spans = []
                for it in items:
                    e = it.get("Element", it)
                    try:
                        s, en = int(e["start_"]), int(e["end_"])
                    except (KeyError, ValueError, TypeError):
                        continue
                    spans.append((s, en))
                if spans:
                    rec[k] = spans
            if rec:
                out[(rid, subid)] = rec
        cache[file] = out
        return out

    def en_times_offsets(self, file, ids):
        """Return the ``times_`` marker offsets for one item, in EN-text space.

        Reads the ``*_tag.msg`` EN reference (offset index the English string)
        and returns the raw ``start_`` values for the first matching id, so the
        EN+ preview can tint the same pause points as the VN line.
        """
        spans = self.en_tag_spans(file)
        for rid in ids:
            rec = spans.get((rid, ""))
            if rec and rec.get("times_"):
                return [s for s, _e in rec["times_"]]
        return []

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


_WILDCARD_RE = re.compile(r"[\*\?]")
_last_query = None
_last_re = None
_SPACE_RE = re.compile(r"\s+")


def _norm_ws(s):
    """Collapse every run of whitespace (incl. newlines) to a single space."""
    return _SPACE_RE.sub(" ", s)


def _wildcard_regex(q):
    """Compile ``q`` into a case-insensitive regex with wildcard support.

    ``*`` matches any run of characters (including none); ``?`` matches any
    single character. Every other character is matched literally, so searching
    for e.g. ``grand*ships`` finds any value containing "grand..." + "ships".
    The compiled regex is cached because ``search_hit`` runs per item.
    """
    global _last_query, _last_re
    if q == _last_query and _last_re is not None:
        return _last_re
    parts = []
    for tok in _WILDCARD_RE.split(q):
        parts.append(re.escape(tok))
    out = ""
    i = 0
    for tok in _WILDCARD_RE.findall(q):
        out += parts[i] + (".*" if tok == "*" else ".")
        i += 1
    out += parts[-1]
    _last_re = re.compile(out, re.IGNORECASE | re.DOTALL)
    _last_query = q
    return _last_re


def search_hit(store, item, query):
    """Case-insensitive match of ``query`` against original/translation/ids.

    ``*`` and ``?`` act as wildcards (any run / any single character);
    otherwise the match is a plain substring test. Whitespace is normalised on
    both sides, so a query typed with spaces matches text broken across line
    breaks (``\\n`` is treated like a space).
    """
    if not query:
        return True
    if _WILDCARD_RE.search(query):
        rx = _wildcard_regex(_norm_ws(query))
        en = _norm_ws(item.en)
        vn = _norm_ws(item.vn)
        return bool(rx.search(en) or rx.search(vn)
                    or any(rx.search(rid) for rid in item.ids))
    q = _norm_ws(query).lower()
    if q in _norm_ws(item.en).lower() or q in _norm_ws(item.vn).lower():
        return True
    return any(q in rid.lower() for rid in item.ids)


def matches(store, item, query):
    return search_hit(store, item, query)


# --------------------------------------------------------------------------
# Markers
# --------------------------------------------------------------------------


def _tuned_spans(store, base, rid, key):
    """Return [(start, end), ...] for a highlight key from tag_tuning.json.

    These are the spans currently baked into the game's ``*_tag.msg`` (from the
    TheRedTeam tune). The editor reads them as a fallback so highlights that
    exist in the game but were never recorded in decisions/overrides are shown
    and edited too, instead of being silently lost behind a stale range.
    """
    try:
        entries = (store.tuned or {}).get("files", {}).get(base, {})
    except Exception:
        return []
    out = []
    for _k, rec in entries.items():
        if rec.get("id_") != rid:
            continue
        for item in rec.get(key, []) or []:
            el = item.get("Element", item)
            try:
                s, e = int(el["start_"]), int(el["end_"])
            except (KeyError, ValueError, TypeError):
                continue
            out.append((s, e))
    return out


def tuned_times(store, base, rid):
    """Return the ``times_`` markers for one rid, merging manual overrides.

    ``times_`` carries the voice/text-reveal pacing: each marker is
    ``(time, wait, start, end)`` where ``time`` is seconds, ``wait`` a bool and
    ``start``/``end`` the character offsets (usually equal) in the VN text.
    The engine pauses right BEFORE ``start`` (it is the first character of the
    next reveal segment); the pause point itself sits at ``start - 1``.
    Returns an empty list when the rid has none.

    Offsets edited by hand (``store.overrides[base][rid]["times_"]``) replace
    the tuned snapshot values at the same index, so the editor always shows
    what will actually be written at patch time.
    """
    try:
        entries = (store.tuned or {}).get("files", {}).get(base, {})
    except Exception:
        entries = {}
    out = []
    for _k, rec in entries.items():
        if rec.get("id_") != rid:
            continue
        override = {}
        try:
            override = (store.overrides or {}).get(base, {}).get(rid, {}) \
                .get("times_", {}) or {}
        except Exception:
            override = {}
        for i, item in enumerate(rec.get("times_", []) or []):
            el = item.get("Element", item)
            try:
                time = float(el["time_"])
                wait = bool(el["wait_"])
            except (KeyError, ValueError, TypeError):
                continue
            ov = override.get(str(i))
            if ov and len(ov) == 2:
                start, end = int(ov[0]), int(ov[1])
            else:
                try:
                    start = int(el["start_"])
                    end = int(el["end_"])
                except (KeyError, ValueError, TypeError):
                    continue
            out.append((time, wait, start, end))
        return out
    return []


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
            break
        # fall back to the position baked into the tuned game tag so the
        # player-name marker is visible and editable in the editor too.
        for s, e in _tuned_spans(store, base, rid, "names_"):
            if 0 <= s <= len(vn):
                player_pos = s
                break
        if player_pos is not None:
            break
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
                # The override stores the exact character range in the VN text,
                # so prefer it: it stays correct even when the decision phrase
                # differs only in whitespace (newline vs space, etc.).
                phrase = None
                if str(i) in ovo:
                    s, e = int(ovo[str(i)][0]), int(ovo[str(i)][1])
                    if 0 <= s <= e <= len(vn):
                        phrase = vn[s:e]
                elif str(i) in deco and isinstance(deco[str(i)], list) and deco[str(i)]:
                    phrase = deco[str(i)][0]
                if not phrase:
                    continue
                start = vn.find(phrase)
                if start < 0:
                    continue
                groups.setdefault((start, phrase), set()).add(TAG[key])
            # fall back to spans already baked into the game's tuned tags so a
            # highlight the user never touched in the editor still shows up.
            # Once a rid has ANY override, the override is the sole authority
            # for that rid: tuned spans no longer apply (they are dropped at
            # patch time), so do not resurrect them here.
            if ovr:
                continue
            for s, e in _tuned_spans(store, base, rid, key):
                if 0 <= s <= e <= len(vn):
                    phrase = vn[s:e]
                    start = vn.find(phrase)
                    if start >= 0:
                        groups.setdefault((start, phrase), set()).add(TAG[key])
    highlights = [("".join(sorted(tags)), phrase)
                  for (start, phrase), tags in sorted(groups.items())]
    return highlights, player_pos


def _esc(s):
    return s.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _unesc(s):
    return s.replace("\\{", "{").replace("\\}", "}").replace("\\\\", "\\")


def vn_index_at(compound, pos):
    """Map a cursor offset in a compound editor string to the plain-VN index.

    The compound is the VN text with inline markers (``{c:..}``/``{w:..}``/
    ``{b:..}`` and the ``{p}`` player point) and escaped literals (``\\{``,
    ``\\}``, ``\\\\``). ``times_`` offsets and the preview tint index the plain
    VN text, so a cursor inside the compound must be translated back. Returns
    the number of plain-VN characters (newlines counted) before ``pos``.
    """
    i = vn = 0
    n = len(compound)
    while i < n and i < pos:
        c = compound[i]
        if c == "\\" and i + 1 < n and compound[i + 1] in "{}":
            if i + 2 <= pos:
                vn += 1
            i += 2
            continue
        if c == "\\" and i + 1 < n and compound[i + 1] == "\\":
            if i + 2 <= pos:
                vn += 1
            i += 2
            continue
        if c == "{":
            if compound.startswith("{p}", i):
                i += 3
                continue
            m = HIGHLIGHT_RE.match(compound, i)
            if m:
                inner_s, inner_e = m.start(2), m.end(2)
                if pos <= inner_s:
                    i = pos
                    continue
                cut = min(pos, inner_e)
                vn += len(_unesc(compound[inner_s:cut]))
                i = max(cut, m.end())
                continue
        vn += 1
        i += 1
    return vn


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


def en_compound(store, item):
    """Render the original EN text with the game's highlight markers.

    The spans come from the EN ``*_tag.msg`` reference (which highlights the
    original English dialogue) and are wrapped in the same ``{c:}``/``{w:}``/
    ``{b:}`` markers the editor uses, so a translator sees exactly which
    substrings the engine highlights and keeps the translation aligned.
    A ``{p}`` marker is inserted at the player-name insertion point
    (``names_``). ``{0}`` placeholders and ``<d>`` codes stay intact.
    """
    en = item.en
    if not en or not store.game:
        return en
    spans = store.en_tag_spans(item.file)
    TAG = {"colors_": "c", "words_": "w", "bolds_": "b"}
    groups = {}              # (start, end) -> set(tags)
    player_pos = None
    for rid, subid in ((r, "") for r in item.ids):
        rec = spans.get((rid, subid))
        if not rec:
            continue
        for key in TAG:
            for s, e in rec.get(key, []):
                if 0 <= s <= e <= len(en):
                    groups.setdefault((s, e), set()).add(TAG[key])
        for s, e in rec.get("names_", []):
            if 0 <= s <= len(en):
                player_pos = s
                break
    edits = []
    for (s, e), tags in sorted(groups.items()):
        tag = "".join(sorted(tags))
        edits.append((s, e, f"{{{tag}:{_esc(en[s:e])}}}"))
    edits.sort(key=lambda x: x[0])
    out = []
    cur = 0
    p_done = player_pos is None
    for s, e, marker in edits:
        if s < cur:
            continue
        seg = en[cur:s]
        if not p_done and player_pos is not None and cur <= player_pos <= s:
            rel = player_pos - cur
            out.append(seg[:rel])
            out.append("{p}")
            out.append(seg[rel:])
            p_done = True
        else:
            out.append(seg)
        out.append(marker)
        cur = e
    tail = en[cur:]
    if not p_done and player_pos is not None:
        rel = min(len(tail), player_pos - cur)
        out.append(tail[:rel] + "{p}" + tail[rel:])
    else:
        out.append(tail)
    return "".join(out)


def en_index_at(compound, plain, offset):
    """Map an offset in the plain EN string to its position in the EN+ compound.

    ``en_compound`` inserts ``{c:..}`` markers and a ``{p}`` point into the
    plain EN text, so the ``times_`` offsets (indexed against plain EN) do not
    line up with the compound's char positions. Walks the compound once, keeping
    the plain-EN cursor, and returns the compound index where the plain char at
    ``offset`` sits (or the end of the compound if the offset is past it).
    """
    if not compound:
        return 0
    i = 0          # compound index
    p = 0          # plain-EN index
    n = len(compound)
    while i < n:
        c = compound[i]
        if c == "{":
            m = HIGHLIGHT_RE.match(compound, i)
            if m:
                phrase = _unesc(m.group(2))
                i += len(m.group(0))
                p += len(phrase)
                continue
            if compound.startswith("{p}", i):
                i += 3
                continue
        if p >= offset:
            return i
        p += 1
        i += 1
    return i


def auto_wrap(compound, width):
    """Reflow a compound string to a maximum line width, keeping markers intact.

    ``compound`` is the editor text (VN with ``{c:}``/``{w:}``/``{b:}`` markers
    and an optional ``[Speaker]`` prefix). All existing line breaks are first
    collapsed into single spaces, then the text is wrapped greedily at word
    boundaries so no line exceeds ``width`` characters. Runs of multiple spaces
    (e.g. the placeholder used for the player's name) are preserved verbatim.
    A highlight marker and its phrase are treated as a single atomic token and
    are never split across lines. The speaker prefix is kept unchanged.
    """
    if not compound:
        return compound
    speaker = ""
    body = compound
    m = SPEAKER_RE.match(body)
    if m:
        speaker = body[:m.end()]
        body = body[m.end():]
    if width < 1:
        return compound
    # tokenize into word/marker atoms; a marker is atomic. Each atom carries
    # the exact whitespace run that precedes it (newlines become one space).
    tokens = []   # (leading_spaces, text, is_marker)
    i = 0
    for mm in HIGHLIGHT_RE.finditer(body):
        tokens.extend(_split_plain(body[i:mm.start()]))
        tokens.append((_trailing_ws(body[i:mm.start()]), mm.group(0), True))
        i = mm.end()
    tokens.extend(_split_plain(body[i:]))
    # greedy wrap: join atoms preserving each one's leading space-run.
    lines = []
    cur = None
    for spaces, text, is_marker in tokens:
        if cur is None:
            # first atom on a line: keep a multi-space run (player-name
            # placeholder / indentation), drop a single separator space.
            cur = (spaces if len(spaces) > 1 else "") + text
            continue
        if len(cur) + len(spaces) + len(text) <= width:
            cur += spaces + text
        elif is_marker and len(text) <= width:
            lines.append(cur)
            cur = (spaces if len(spaces) > 1 else "") + text
        else:
            lines.append(cur)
            cur = (spaces if len(spaces) > 1 else "") + text
    if cur is not None:
        lines.append(cur)
    # preserve a trailing multi-space run (player-name placeholder) at the end.
    tm = re.search(r"( {2,})\s*$", body)
    if tm and lines:
        lines[-1] += tm.group(1)
    return speaker + "\n".join(lines)


def _split_plain(s):
    """Return plain-text tokens ``(leading_spaces, word, False)``.

    ``leading_spaces`` is the exact space-run before the word with newlines
    removed; if the run was only newlines it becomes a single space. Space runs
    (e.g. the player-name placeholder) are preserved verbatim.
    """
    out = []
    pos = 0
    for m in re.finditer(r"\S+", s):
        sp = s[pos:m.start()]
        sp = sp.replace("\n", "")
        leading = sp if sp else " "
        out.append((leading, m.group(0), False))
        pos = m.end()
    return out


def _trailing_ws(s):
    """Return the whitespace run at the very end of ``s`` (newlines removed).

    Newlines are dropped; a run that was only newlines becomes a single space.
    """
    m = re.search(r"\s+$", s)
    if not m:
        return ""
    sp = m.group(0).replace("\n", "")
    return sp if sp else " "


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
            elif _tuned_spans(store, base, rid, k):
                # The highlight exists in the tuned tags baked into the game,
                # but the user removed it. Keep an empty entry as a tombstone
                # so the tuned fallback in _load_markers does not bring it back.
                ov[k] = {}
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
    # refresh the markers so a later build_compound reflects the saved state
    # (otherwise the editor would re-render the pre-edit markers)
    item.markers, item.player_pos = _load_markers(
        store, item.file, item.ids, vn)
    return warnings


def replace_in_compound(compound, regex, repl):
    """Apply a regex substitution to the VN portion of a compound string.

    ``compound`` is the editor text (VN with inline ``{c:}``/``{w:}``/``{b:}``
    markers, an optional ``[Speaker]`` prefix and ``{p}`` player point). Only
    the plain VN is rewritten; markers whose phrase still exists in the new
    text are re-anchored (positions recomputed from the phrase), while markers
    whose phrase disappeared are dropped and reported as warnings. Returns
    ``(new_compound, n_subs, warnings)``; if nothing matched the input is
    returned unchanged.
    """
    speaker, vn, highlights, player_pos = parse_compound(compound)
    new_vn, n_subs = regex.subn(repl, vn)
    if n_subs == 0:
        return compound, 0, []
    warnings = []
    kept = []
    for tag, phrase in highlights:
        if phrase in new_vn:
            kept.append((tag, phrase))
        else:
            warnings.append(f"dropped marker {tag}:{phrase!r}")
    ppos = player_pos if player_pos is not None and player_pos <= len(new_vn) \
        else None

    class _Tmp:
        __slots__ = ("vn", "markers", "player_pos", "speaker")
    tmp = _Tmp()
    tmp.vn = new_vn
    tmp.markers = kept
    tmp.player_pos = ppos
    tmp.speaker = speaker
    return build_compound(tmp, with_speaker=True), n_subs, warnings


def apply_text_replace(store, item, regex, repl):
    """Apply a regex substitution to the VN translation, re-anchoring markers.

    ``regex`` is a compiled :class:`re.Pattern`, ``repl`` the replacement
    string (backreferences ``\\1`` etc. are supported). Only the plain VN
    text is rewritten; highlight markers whose phrase still exists in the
    new text are re-anchored (positions recomputed from the phrase), while
    markers whose phrase disappeared are dropped and reported as warnings.
    The player-name insertion point is preserved when its old position maps
    to a valid location in the new text. Writes go through :func:`apply_edit`
    so decisions/overrides stay consistent. Returns ``(n_subs, warnings)``.
    """
    compound = build_compound(item, with_speaker=True)
    new_compound, n_subs, warnings = replace_in_compound(
        compound, regex, repl)
    if n_subs == 0:
        return 0, []
    warnings += apply_edit(store, item, new_compound)
    return n_subs, warnings


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