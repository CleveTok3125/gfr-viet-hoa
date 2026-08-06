"""tag_tuning.json: the single source of truth for dialogue tag files.

Instead of relying on per-machine disk state, the tuned `*_tag.msg` files are
snapshotted into a git-tracked JSON file (`tag_tuning.json`). `apply.py`
recreates the loose tag tables on the target install from this JSON, so an
end-user does not need to run `remap_tags` by hand and a fresh install gets
the exact tune the translation author produced (independent of old disk data).

Evolution model
---------------
tag_tuning.json mirrors the *tuned* tag tables produced by TheRedTeam's exe
plus our Vietnamese remap. Later tag edits (a new `remap_tags --write`, a
manual tweak) overwrite the affected entries inside the JSON; entries that are
not overwritten keep working unchanged. To refresh only the changed entries,
dump a fresh copy and merge it over the existing file (`--merge`).

Format
------
    {
      "version": 1,
      "files": {
        "<file_base>": {
          "<id_>::<subid_>": {
            "id_": "...",
            "subid_": "...",
            "bolds_":  [ {"Element": {...}}, ... ],
            "colors_": [ {"Element": {...}}, ... ],
            ...                     # only keys present in the entry
          }
        }
      }
    }

The `Element` payload under each tag key is kept verbatim (msgpack -> JSON)
so `write_to_game` reconstructs a byte-equivalent msgpack table. Keys are
`id_`/`subid_`; within a file these are unique (verified), so the keyed map is
lossless. Order of entries is not significant to the game (lookup by id).
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from remap_tags import load_tag, save_tag
from common import load_filelist


KEY_SEP = "::"


def _entry_key(el):
    return f"{el.get('id_', '')}{KEY_SEP}{el.get('subid_', '')}"


def _clean(value):
    """Return msgpack value mapped to something JSON-serializable as-is."""
    return value


def tag_ko_paths(game_dir):
    """Yield the game-relative ko/ *_tag.msg paths present on disk."""
    out = []
    for rel in load_filelist():
        if not rel.endswith("_tag.msg"):
            continue
        if not (rel.startswith("system/table/text/ko/") or
                rel.startswith("system/table/scenario/ko/")):
            continue
        if os.path.isfile(os.path.join(game_dir, "data", rel)):
            out.append(rel)
    return sorted(out)


def dump_from_game(game_dir):
    """Read every on-disk ko/ *_tag.msg and return the tag_tuning structure."""
    files = {}
    dirs = {}
    for rel in tag_ko_paths(game_dir):
        base = os.path.basename(rel)[: -len("_tag.msg")]
        blob = load_tag(os.path.join(game_dir, "data", rel))
        entries = {}
        for entry in blob["Tag"]["tags_"]:
            el = entry["Element"]
            items = {}
            for k in ("bolds_", "colors_", "words_", "names_", "times_",
                      "bgms_", "vols_", "fades_", "icons_", "formats_",
                      "dynamics_", "alignments_", "copyrights_"):
                if k in el and el[k]:
                    items[k] = _clean(el[k])
            rec = {"id_": el.get("id_", ""), "subid_": el.get("subid_", "")}
            rec.update(items)
            entries[_entry_key(el)] = rec
        files[base] = entries
        dirs[base] = "text" if "/text/" in rel else "scenario"
    return {"version": 1, "files": files, "dirs": dirs}


def _dir_of(game_dir, data, base):
    """Return the ko subdir ('text' or 'scenario') for a file base."""
    d = (data.get("dirs") or {}).get(base)
    if d:
        return d
    for seed in ("system/table/text/ko/", "system/table/scenario/ko/"):
        if os.path.isdir(os.path.join(game_dir, "data", seed)):
            return "text" if "text" in seed else "scenario"
    return None


def load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def merge(existing, fresh):
    """Overwrite entries in `existing` with those in `fresh` (by file, id)."""
    existing = dict(existing)
    for base, entries in (fresh.get("files") or {}).items():
        cur = existing.setdefault("files", {}).setdefault(base, {})
        cur.update(entries)
    existing["version"] = fresh.get("version", existing.get("version", 1))
    return existing


SPAN_KEYS = ("bolds_", "colors_", "words_", "names_")


def _apply_overrides(entries, overrides, base):
    """Apply manual VN ranges from `overrides` onto `entries` in place.

    `overrides` is the tag_overrides.json shape
    {base: {rid: {tag_key: {item_idx: [start, end]}}}}.

    For any rid present in `overrides`, the override is the sole authority for
    the span keys it defines: its ranges replace the baked-in tuned spans, and
    any tuned span key the override does not define is dropped (the rid was
    hand-edited, so tag_tuning no longer applies to it). Element metadata
    (``color_``/``wordID_``/``type_``) is carried over from the old tuned span
    at the same index when available, so glossary links and colors survive.

    Returns the count of ranges stamped or dropped.
    """
    if not overrides:
        return 0
    file_over = overrides.get(base) or {}
    if not file_over:
        return 0
    n_stamped = 0
    # entries keyed by "id::subid"; override rid keys on the entry id_ only.
    for _, rec in entries.items():
        rid = rec.get("id_", "")
        id_over = file_over.get(rid)
        if not id_over:
            continue
        for k in SPAN_KEYS:
            kmap = id_over.get(k)
            old_spans = rec.get(k, [])
            if kmap is None:
                # rid was edited but this key has no override -> drop tuned
                rec.pop(k, None)
                if old_spans:
                    n_stamped += len(old_spans)
                continue
            if not kmap:
                # Empty dict = tombstone: user removed this highlight entirely.
                rec.pop(k, None)
                n_stamped += 1
                continue
            new_spans = []
            for idx, (ns, ne) in kmap.items():
                idx = int(idx)
                meta = {}
                if idx < len(old_spans):
                    old = old_spans[idx].get("Element", old_spans[idx])
                    meta = {m: v for m, v in old.items()
                            if m not in ("start_", "end_")}
                elem = dict(meta)
                elem["start_"] = str(int(ns))
                elem["end_"] = str(int(ne))
                new_spans.append({"Element": elem})
                n_stamped += 1
            rec[k] = new_spans
    return n_stamped


def write_to_game(game_dir, data, index_path=None, overrides=None):
    """Write every tag table in `data` to the ko/ dirs.

    When `overrides` (tag_overrides.json, see _apply_overrides) is given, the
    manual highlight VN ranges are stamped onto the entries before writing.
    Returns a tuple ``(changed_rels, n_stamped)``: the game-relative paths of
    the tag tables written and the number of manual ranges stamped.
    """
    import datai

    changed = []
    total_stamped = 0
    for base, entries in (data.get("files") or {}).items():
        kind = _dir_of(game_dir, data, base)
        if kind is None:
            continue
        total_stamped += _apply_overrides(entries, overrides, base)
        rel_dir = f"system/table/{kind}/ko/"
        path = os.path.join(game_dir, "data", rel_dir, base + "_tag.msg")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tags = []
        for rec in entries.values():
            el = {"id_": rec.get("id_", ""), "subid_": rec.get("subid_", "")}
            for k in ("bolds_", "colors_", "words_", "names_", "times_",
                      "bgms_", "vols_", "fades_", "icons_", "formats_",
                      "dynamics_", "alignments_", "copyrights_"):
                if k in rec:
                    el[k] = rec[k]
            tags.append({"Element": el})
        blob = {"Tag": {"tags_": tags}}
        save_tag(path, blob)
        changed.append(os.path.join(rel_dir, base + "_tag.msg"))

    if index_path and changed:
        datai.fix_sizes(game_dir, index_path, changed)
    return (changed, total_stamped)


def main():
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", required=True, help="game directory")
    ap.add_argument("--dump", metavar="OUT", help="write tuned tags to OUT (tag_tuning.json)")
    ap.add_argument("--merge", metavar="OUT",
                    help="merge a freshly dumped file into OUT, printing changed count")
    ap.add_argument("--write", action="store_true",
                    help="write tag_tuning.json (next to --dump/--merge) into the game")
    args = ap.parse_args()

    if args.dump:
        data = dump_from_game(args.game)
        save(args.dump, data)
        files = len(data["files"])
        print(f"dumped {files} tag file(s) -> {args.dump}")

    if args.merge:
        fresh = dump_from_game(args.game)
        existing = load(args.merge) if os.path.exists(args.merge) else {"files": {}}
        before = sum(len(v) for v in (existing.get("files") or {}).values())
        merged = merge(existing, fresh)
        save(args.merge, merged)
        after = sum(len(v) for v in (merged.get("files") or {}).values())
        print(f"merged: {before} -> {after} entries -> {args.merge}")

    if args.write:
        src = args.merge or args.dump
        if not src:
            ap.error("--write needs --dump or --merge")
        data = load(src)
        from common import find_game_dir
        game = args.game or find_game_dir()
        index_path = os.path.join(game, "data.i")
        changed, _stamped = write_to_game(game, data, index_path)
        print(f"wrote {len(changed)} tag file(s) to game, sizes fixed")


if __name__ == "__main__":
    main()