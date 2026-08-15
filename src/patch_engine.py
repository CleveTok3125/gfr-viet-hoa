"""Core translation engine for Granblue Fantasy: Relink .msg tables.

A .msg file is a msgpack map with a ``rows_`` list; each row has
``column_.text_`` holding the display string, plus ``column_.id_hash_`` and
``column_.subid_hash_`` — stable engine ids that survive game updates. The
engine walks those rows and writes the Vietnamese value looked up by row id,
so no English text is ever stored in the repository (the English reference is
read from the user's own game at patch time).

For skillboard rows of the form ``Name:\\n<stat>`` (e.g. ``Launch, Air
Combo, and Aerial Barrage:\\nDMG Cap +{0}%``), the stat line is a template
whose ``{0}`` is filled by the engine at runtime. The row is translated by
keeping the English name and substituting the stat phrase, using the stat-only
rows that carry a translation in the same table (this reproduces the former
``rules.json`` node transform without storing any English game text).

Only rows whose final value differs from the source are rewritten.
"""
import re
from typing import cast

import msgpack

SEP = "::"


def row_key(row_id, subid):
    """Stable dict key for a row: id alone, or id::subid when split."""
    return row_id if not subid else f"{row_id}{SEP}{subid}"


def read_msg(path):
    """Unpack a .msg table from a file path or raw bytes."""
    if isinstance(path, (bytes, bytearray)):
        raw = bytes(path)
    else:
        with open(path, "rb") as fh:
            raw = fh.read()
    return msgpack.unpackb(raw, raw=False)


def write_msg(path, data):
    raw = cast(bytes, msgpack.packb(data))
    with open(path, "wb") as fh:
        fh.write(raw)


def final_text(translation, en_text):
    """Choose the row text for the two-stage patch.

    The Korean slot is redirected to English first, then Vietnamese is
    overwritten on top: a row shows its Vietnamese translation when one
    exists, otherwise the game's own English text (so untranslated rows are
    never left in Korean). An empty / whitespace-only translation counts as
    "not translated" and falls back to the English reference too, so a blank
    stored value is never written into the game. Returns ``None`` only when
    neither a translation nor a usable English reference is available.
    """
    if translation and translation.strip():
        return translation
    if en_text and en_text.strip():
        return en_text
    return None


_STAT_HEAD_RE = re.compile(r".+: ?$")
_STAT_FILE = "text_skillboard.msg"


class PatchEngine:
    """ID-keyed translation engine.

    ``translations`` is ``{filename: {id | id::subid: vi}}``.
    """

    def __init__(self, translations):
        self.translations = translations
        self._stat_re_cache = {}

    def _stat_rule(self, file, rows):
        """Return ``(node_re, stat_vn)`` for the skillboard stat fallback.

        ``rows`` is a list of ``(id_hash_, subid_hash_, text_)`` from the
        English source. A stat line is identified as an English string that
        (a) appears as the tail (after the last newline) of some composite
        ``Name:\\n<stat>`` row and (b) carries a translation in the table.
        The regex reproduces the exact shape the old rules.json matched.
        """
        if file in self._stat_re_cache:
            return self._stat_re_cache[file]
        result = (None, {})
        if file == _STAT_FILE:
            tbl = self.translations.get(file) or {}
            tails = set()
            for _rid, _sub, text in rows:
                nl = text.rfind("\n")
                if nl > 0 and _STAT_HEAD_RE.match(text[:nl]):
                    tails.add(text[nl + 1:])
            text_by_key = {row_key(r, s): t for r, s, t in rows}
            stat_vn = {}
            for key, vn in tbl.items():
                t = text_by_key.get(key)
                if t is not None and t in tails:
                    stat_vn[t] = vn
            if stat_vn:
                pattern = "|".join(re.escape(s) for s in stat_vn)
                result = (re.compile(r"^(.+?): ?\n(" + pattern + r")$"), stat_vn)
        self._stat_re_cache[file] = result
        return result

    def transform(self, file, rid, subid, text, stat_rule=None):
        """Return the Vietnamese string for a row, or None if unknown."""
        tbl = self.translations.get(file) or {}
        key = row_key(rid, subid)
        if key in tbl:
            return tbl[key]
        node_re, stat_vn = stat_rule or (None, {})
        if node_re:
            m = node_re.match(text)
            if m:
                return f"{m.group(1)}:\n{stat_vn[m.group(2)]}"
        return None

    def patch_file(self, file, path):
        """Apply translations to the .msg file at ``path``.

        Matches rows by their own row ids; the stat fallback derives stat
        lines from the file's English texts when they are English (for loose
        fallback installs the disk text may already be Vietnamese, in which
        case the fallback simply finds nothing, as before).

        Returns dict(patched, already, unmatched, rows).
        """
        data = read_msg(path)
        rows = [
            (r["column_"].get("id_hash_", ""),
             r["column_"].get("subid_hash_", ""),
             r["column_"].get("text_", ""))
            for r in data["rows_"]
            if isinstance(r.get("column_", {}).get("text_"), str)
        ]
        stat_rule = self._stat_rule(file, rows)
        patched = already = 0
        unmatched = []
        for row, (rid, subid, text) in zip(data["rows_"], rows):
            new = self.transform(file, rid, subid, text, stat_rule)
            if not new:
                # no (non-empty) translation available: leave the row as-is
                unmatched.append(text)
            elif new == text:
                already += 1
            else:
                row["column_"]["text_"] = new
                patched += 1
        if patched:
            write_msg(path, data)
        return {
            "file": file,
            "path": path,
            "patched": patched,
            "already": already,
            "unmatched": unmatched,
        }

    def iter_files(self):
        return sorted(self.translations.keys())