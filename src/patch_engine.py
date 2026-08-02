"""Core translation engine for Granblue Fantasy: Relink .msg tables.

A .msg file is a msgpack map with a `rows_` list; each row has
`column_.text_` holding the display string. The engine walks those rows
and applies, in order:

  1. exact-match from the per-file EN->VI table,
  2. node-transform rules (e.g. skillboard `Name:\n<stat>` rows),
  3. format-aware transforms defined in rules.json.

Only rows whose final value differs from the source are rewritten.
"""
import re

import msgpack


def read_msg(path):
    """Unpack a .msg table from a file path or raw bytes."""
    if isinstance(path, (bytes, bytearray)):
        raw = bytes(path)
    else:
        with open(path, "rb") as f:
            raw = f.read()
    return msgpack.unpackb(raw, raw=False)


def write_msg(path, data):
    raw = msgpack.packb(data)
    with open(path, "wb") as f:
        f.write(raw)


class PatchEngine:
    def __init__(self, translations, rules):
        self.translations = translations  # {filename: {en: vi}}
        self.rules = rules or {}
        self.stat_map = (self.rules.get("stat_map") or {})
        self._node_re = self._build_node_re()

    def _build_node_re(self):
        stats = list(self.stat_map.keys())
        if not stats:
            return None
        return re.compile(r"^(.+?): ?\n(" + "|".join(re.escape(s) for s in stats) + r")$")

    def _transform(self, text, file):
        """Return the Vietnamese string for `text`, or None if unknown."""
        tbl = self.translations.get(file)
        if tbl and text in tbl:
            return tbl[text]
        if self._node_re and file in (self.rules.get("skillboard_node_transform") or {}).get("files", []):
            m = self._node_re.match(text)
            if m:
                name, stat = m.groups()
                return f"{name}:\n{self.stat_map[stat]}"
        return None

    def patch_file(self, file, path):
        """Apply translations to the .msg file at `path`.

        Returns dict(patched, already, unmatched, rows).
        """
        data = read_msg(path)
        patched = already = 0
        unmatched = []
        for row in data["rows_"]:
            t = row["column_"]["text_"]
            new = self._transform(t, file)
            if new is None:
                unmatched.append(t)
            elif new == t:
                already += 1
            else:
                row["column_"]["text_"] = new
                patched += 1
        write_msg(path, data) if patched else None
        return {
            "file": file,
            "path": path,
            "patched": patched,
            "already": already,
            "unmatched": unmatched,
        }

    def iter_files(self):
        return sorted(self.translations.keys())
