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

import copy
import functools
import os
import re
import sys

import jsonio as json

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, ".."))

import msgpack

from common import bootstrap

bootstrap()

from common import load_translations, repo_file

SEP = "::"
HIGHLIGHT_KEYS = ("colors_", "words_", "bolds_")


def row_key(row_id, subid):
    """Stable table key for a row: id alone, or id::subid when split."""
    return row_id if not subid else f"{row_id}{SEP}{subid}"


def split_key(key):
    """Return (id_hash_, subid_hash_) for a stored table key."""
    rid, _sep, sub = key.rpartition(SEP)
    if _sep:
        return rid, sub
    return key, ""
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

# Cache file storing the extracted EN id->text maps so a second editor boot
# (or any tool that builds the scan index) can skip the LZ4 + msgpack decode
# that dominates the build. Lives in the repo's writable ``data/`` dir and is
# keyed by the game install path; see ``scripts/bench_scan_cache.py``.
SCAN_CACHE_REL = os.path.join("data", ".scan_index.cache.json")


class ScanCache:
    """Persistent store of extracted EN id->text maps, keyed by digest.

    Each :meth:`Store.id_text_map` result is derived from one game archive
    chunk; the digest (:func:`extract.chunk_digest`) is an xxh64 of the
    still-compressed chunk bytes, so a cached map can be trusted after one
    cheap file read + hash instead of re-running the decompress/decode
    pipeline. Layout: ``{file: {"digest": int, "id_text": {key: en_text}}}``
    plus the absolute game dir (a different install must not reuse maps).
    """

    VERSION = 1

    def __init__(self, path=None, game_dir=None):
        self.path = path or os.path.join(os.path.dirname(_HERE), SCAN_CACHE_REL)
        self.game_dir = os.path.realpath(game_dir) if game_dir else ""
        self.tables = {}
        self._dirty = False
        self._load()

    def _load(self):
        try:
            with open(self.path, "rb") as fh:
                data = fh.read()
        except OSError:
            return
        try:
            payload = json.loads(data)
        except (OSError, ValueError):
            return
        if payload.get("version") != self.VERSION or \
                payload.get("game_dir") != self.game_dir:
            return
        self.tables = payload.get("tables", {})

    def get(self, file, digest):
        ent = self.tables.get(file)
        if ent is not None and ent.get("digest") == digest:
            return ent.get("id_text")
        return None

    def put(self, file, digest, id_text):
        self.tables[file] = {"digest": digest, "id_text": id_text}
        self._dirty = True

    def save(self):
        if not self._dirty:
            return
        payload = {"version": self.VERSION, "game_dir": self.game_dir,
                   "tables": self.tables}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, self.path)
        self._dirty = False


class Store:
    """Handles the three authoring JSONs and, optionally, the game archive."""

    def __init__(self, game_dir=None, use_cache=True, cache_path=None):
        self.game = game_dir
        self.translations = load_translations()
        self.tables = self.translations.get("translations", {})
        self.decisions = self._load_json("highlight_decisions.json")
        self.overrides = self._load_json("tag_overrides.json")
        self.tuned = self._load_json("tag_tuning.json")  # spans baked into game
        self.speakers = self._load_json("data/scenario_speakers.json")
        self._id_cache = {}
        self.scan_rows = None  # cached per-row scan descriptors (see scan_index)
        # Persistent EN-map cache (skips the game LZ4+decode on the next boot);
        # only active when a game dir is supplied. ``cache_hits`` /
        # ``cache_misses`` / ``cache_served`` let a caller report the result.
        self.cache = ScanCache(path=cache_path, game_dir=game_dir) \
            if (game_dir and use_cache) else None
        self._cache_served = set()  # tables whose map this session hit the cache
        self.cache_hits = 0
        self.cache_misses = 0
        # path -> Store index for atomic saves
        self._paths = {
            "translations.json": repo_file("translations.json"),
            "highlight_decisions.json": repo_file("highlight_decisions.json"),
            "tag_overrides.json": repo_file("tag_overrides.json"),
        }

    @staticmethod
    def _load_json(rel):
        p = os.path.join(os.path.dirname(_HERE), rel)
        if not os.path.isfile(p):
            return {}
        with open(p, "rb") as fh:
            return json.load(fh)

    def scan_index(self, progress=None):
        """Return the per-row :class:`ScanRow` list, building it on first use.

        Every row of every table gets one descriptor with the normalized
        search keys precomputed, so a table refresh filters plain strings
        instead of re-running ``_norm_key`` / ``tr_state`` / dict lookups for
        the whole store on every keypress. The store's caches (id -> EN,
        tuned times) are immutable for a session, so the index only needs
        rebuilding after a save mutates the authoring data (the caller sets
        ``scan_rows = None`` at the same point it invalidates ``_dup_sync``).

        ``progress`` is an optional ``callable(file, done, total, phase,
        size)`` invoked once per phase per table while the index is being
        built, so a UI can report what the build is doing. ``phase`` is
        ``"extract"`` (the English reference table is being pulled from the
        game install), ``"cache"`` (it came from the persistent
        :class:`ScanCache` instead), ``"normalize"`` (the row keys are being
        normalized) or ``"done"`` (the table finished); ``done`` counts the
        rows processed so far (before ``"done"``, including the current table
        after it) and ``size`` is the number of rows in the current table.

        A cache-enabled store persists the freshly extracted maps (one digest
        per table) before returning, so the next boot is the fast path.
        """
        if self.scan_rows is None:
            total = sum(len(t) for t in self.tables.values()) if progress else 0
            done = 0
            rows = []
            for file, table in self.tables.items():
                size = len(table)
                if progress:
                    progress(file, done, total, "extract", size)
                self.id_text_map(file)
                if progress:
                    phase = "cache" if file in self._cache_served else "normalize"
                    progress(file, done, total, phase, size)
                for idx, (key, vn) in enumerate(table.items()):
                    rows.append(ScanRow(self, file, key, vn, idx))
                done += size
                if progress:
                    progress(file, done, total, "done", size)
            self.scan_rows = rows
            if self.cache is not None:
                self.cache.save()
        return self.scan_rows

    # -- id / speaker resolution ------------------------------------------

    def id_text_map(self, file):
        """Return {row_key: en_text} for a table (EN source).

        ``row_key`` is the id-keyed table key: ``id_hash_`` for a single row,
        ``id_hash_::subid_hash_`` when the id is split across rows. This is
        the forward map that resolves a stored row id back to its English
        text for preview/search when a game dir is supplied.

        With a :class:`ScanCache`, the map is first looked up by the digest
        of the game chunk it was extracted from: on a hit the LZ4 + msgpack
        decode is skipped entirely, and on a miss the fresh map is persisted
        for the next boot.
        """
        if file in self._id_cache:
            return self._id_cache[file]
        if not self.game:
            self._id_cache[file] = {}
            return {}
        kind = "scenario" if file.startswith("text_scenario") else "text"
        rel = f"system/table/{kind}/en/{file}"
        digest = None
        if self.cache is not None:
            digest = self._chunk_digest(rel)
            if digest is not None:
                cached = self.cache.get(file, digest)
                if cached is not None:
                    self.cache_hits += 1
                    self._cache_served.add(file)
                    self._id_cache[file] = cached
                    return cached
                self.cache_misses += 1
        raw = self._extract(rel)
        m = {}
        if raw:
            try:
                rows = msgpack.unpackb(raw, raw=False)["rows_"]
            except Exception:  # noqa: BLE001 - decode failures fall back to no rows
                rows = []
            for r in rows:
                c = r.get("column_", {})
                tx = c.get("text_", "")
                key = row_key(c.get("id_hash_", ""), c.get("subid_hash_", ""))
                if tx and key:
                    m[key] = tx
        self._id_cache[file] = m
        if self.cache is not None and digest is not None:
            self.cache.put(file, digest, m)
        return m

    def _extract(self, rel):
        if not self.game:
            return None
        try:
            from extract import extract
        except ImportError:
            return None
        return extract(self.game, rel, self._index_bytes())

    def _index_bytes(self):
        """data.i bytes, read once per session (shared by extract/digest)."""
        if getattr(self, "_datai", None) is None:
            self._datai = None
            if self.game:
                p = os.path.join(self.game, "data.i")
                if os.path.isfile(p):
                    with open(p, "rb") as fh:
                        self._datai = fh.read()
        return self._datai

    def _chunk_digest(self, rel):
        """xxh64 of the compressed game chunk for ``rel`` (None unavailable)."""
        try:
            from extract import chunk_digest
        except ImportError:
            return None
        return chunk_digest(self.game, rel, self._index_bytes())

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
                except Exception:  # noqa: BLE001 - decode failures fall back to no rows
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
            for k in ("name_en", "name_ja", "chara"):
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
        except Exception:  # noqa: BLE001 - corrupt tag table yields empty spans
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
        self._atomic("highlight_decisions.json", self.decisions)
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
            json.dump(data, fh, ensure_ascii=False, indent=2)
            if has_nl:
                fh.write("\n")
        os.replace(tmp, p)


# --------------------------------------------------------------------------
# Items
# --------------------------------------------------------------------------


class Item:
    """One translatable entry with its resolved identity + markers."""

    __slots__ = (
        "en",
        "file",
        "ids",
        "key",
        "markers",
        "player_pos",
        "speaker",
        "subid",
        "vn",
    )

    def __init__(self, store, file, key, vn):
        self.file = file
        self.key = key
        self.vn = vn
        rid, self.subid = split_key(key)
        self.ids = [rid] if rid else []
        self.en = store.id_text_map(file).get(key, "")
        self.speaker = store.speaker_label(self.ids)
        self.markers, self.player_pos = _load_markers(
            store, file, self.ids, vn)


def iter_items(store, bases=None, holds=None):
    """Yield every item of the chosen table files.

    ``bases`` restricts to a set of table basenames; ``holds`` is an optional
    dict reused to keep one Item per (file,key) across calls.
    """
    tables = store.tables
    bases = set(bases) if bases else None
    for file, table in tables.items():
        base = file[:-len(".msg")]
        if bases is not None and base not in bases:
            continue
        for key, vn in table.items():
            kk = (file, key)
            it = holds.get(kk) if holds else None
            if it is None:
                it = Item(store, file, key, vn)
                if holds is not None:
                    holds[kk] = it
            yield it


class ScanItem:
    """Lightweight table row: enough to filter + render, no markers yet.

    Used by the editor only (never escaped to disk). Markers/player_pos are
    resolved lazily via :meth:`materialize` when an item is actually opened,
    so a full-text table scan stays cheap. ``en_norm`` / ``vn_norm`` /
    ``ids_low`` are precomputed search keys (populated from a
    :class:`ScanRow`); when present, :func:`search_hit` matches against them
    directly instead of re-normalizing every row.
    """

    __slots__ = (
        "en",
        "en_norm",
        "file",
        "has_times",
        "ids",
        "ids_low",
        "key",
        "speaker",
        "subid",
        "tr",
        "vn",
        "vn_norm",
    )

    def __init__(self, store, file, key, vn):
        self.file = file
        self.key = key
        self.vn = vn
        rid, self.subid = split_key(key)
        self.ids = [rid] if rid else []
        self.en = store.id_text_map(file).get(key, "")
        self.speaker = store.speaker_label(self.ids)
        self.en_norm = None
        self.vn_norm = None
        self.ids_low = None
        self.has_times = None
        self.tr = None

    def materialize(self, store):
        """Promote to a full :class:`Item` (loads markers for one row)."""
        return Item(store, self.file, self.key, self.vn)


class ScanRow:
    """Precomputed search/render fields for one table row.

    Built once per store (:meth:`Store.scan_index`) and reused across table
    refreshes, so filtering reads plain normalized strings instead of
    re-normalizing the whole store on every keypress. The store's caches are
    immutable for a session, so the index only needs rebuilding after a save
    mutates the authoring data.
    """

    __slots__ = (
        "en_norm",
        "file",
        "has_times",
        "ids_low",
        "idx",
        "key",
        "rid",
        "speaker_low",
        "tr",
        "vn",
        "vn_norm",
    )

    def __init__(self, store, file, key, vn, idx):
        self.file = file
        self.key = key
        self.vn = vn
        self.idx = idx
        rid, _sub = split_key(key)
        self.rid = rid
        self.ids_low = [rid.lower()] if rid else []
        en = store.id_text_map(file).get(key, "")
        self.en_norm = _norm_key(en)
        self.vn_norm = _norm_key(vn)
        self.speaker_low = (store.speaker_label([rid]) or "").lower() if rid else ""
        self.tr = tr_state(vn)
        self.has_times = bool(
            tuned_times_index(store).get(file[:-len(".msg")], {}).get(rid))


def iter_scan(store, bases=None):
    """Yield a :class:`ScanItem` for every row, skipping marker loading.

    ``bases`` restricts to a set of table basenames. The id -> EN map is
    cached per file inside the store, so a full scan never re-reads a table.
    """
    tables = store.tables
    bases = set(bases) if bases else None
    for file, table in tables.items():
        base = file[:-len(".msg")]
        if bases is not None and base not in bases:
            continue
        for key, vn in table.items():
            yield ScanItem(store, file, key, vn)


# --------------------------------------------------------------------------
# Duplicate groups (same file, exact EN, same source tag/times)
# --------------------------------------------------------------------------


class GroupMember:
    """One row of a duplicate group (same file, EN + source tag/times).

    Lightweight like :class:`ScanItem`; promoted to a full :class:`Item`
    (markers loaded) only when actually edited via :meth:`materialize`.
    ``idx_file`` is the row's enumeration index inside its own table (the N
    column when the file filter is active); ``idx_global`` is the enumeration
    index over all tables (the N column in the all-files view).
    """

    __slots__ = (
        "en",
        "file",
        "ids",
        "idx_file",
        "idx_global",
        "key",
        "speaker",
        "subid",
        "vn",
    )

    def __init__(self, store, file, key, vn, idx_file, idx_global):
        self.file = file
        self.key = key
        self.vn = vn
        self.idx_file = idx_file
        self.idx_global = idx_global
        rid, self.subid = split_key(key)
        self.ids = [rid] if rid else []
        self.en = store.id_text_map(file).get(key, "")
        self.speaker = store.speaker_label(self.ids)

    def materialize(self, store):
        """Promote to a full :class:`Item` (loads markers for one row)."""
        return Item(store, self.file, self.key, self.vn)


def _member_signature(store, member):
    """``(file, en, tag_sig, times_sig)`` used as the duplicate-group key.

    ``tag_sig`` is the EN-source highlight/name spans (``en_tag_spans``) merged
    over the member's rids; ``times_sig`` the EN-source ``times_`` offsets. Both
    come from the game install, so rows that are only *visually* the same text
    but carry different tag/times data at the source stay separate.
    """
    spans = store.en_tag_spans(member.file)
    tag_sig = []
    for rid in member.ids:
        rec = spans.get((rid, ""))
        if not rec:
            continue
        for key in HIGHLIGHT_KEYS + ("names_",):
            items = rec.get(key)
            if items:
                tag_sig.append((key, tuple(sorted(items))))
    tag_sig = tuple(sorted(tag_sig))
    times_sig = tuple(sorted(store.en_times_offsets(member.file, member.ids)))
    return (member.file, member.en, tag_sig, times_sig)


def authored_signature(store, member):
    """The authored state of one row: translation + decisions + overrides.

    Mirrors :func:`_member_signature` (which compares the EN-source data) but
    on the *authored* side, so a ``✓`` in the duplicate list means the member
    is fully in sync with the canonical member — a group save or voice-sync
    stamp would write nothing new for it. ``times_`` overrides are included
    because the voice-sync panel targets the whole group. Each record is
    canonicalised with sorted-key JSON, so the comparison is exact and stable.
    """
    base = member.file[:-len(".msg")]
    # Read the live translation (not the possibly-stale ``member.vn`` cached in
    # the group index), so the check reflects the last save immediately.
    vn = (store.tables.get(member.file, {}) or {}).get(member.key, "")
    dec = json.dumps(
        [(store.decisions or {}).get(base, {}).get(rid, {})
         for rid in member.ids],
        sort_keys=True, ensure_ascii=False)
    ov = json.dumps(
        [(store.overrides or {}).get(base, {}).get(rid, {})
         for rid in member.ids],
        sort_keys=True, ensure_ascii=False)
    return (vn, dec, ov)


def duplicate_groups(store):
    """Index duplicate rows: same file, exact EN, same source tag/times.

    Returns ``{signature: [GroupMember, ...]}`` for groups with >= 2 members.
    EN text and the source spans are read from the game install, so without a
    game dir the result is empty. Cached on the store for the session (the EN /
    tag / times data never change while the editor is running).
    """
    cache = getattr(store, "_dup_groups", None)
    if cache is not None:
        return cache
    groups = {}
    if store.game:
        idx_global = 0
        for file, table in store.tables.items():
            idx_file = 0
            for key, vn in table.items():
                member = GroupMember(store, file, key, vn,
                                     idx_file, idx_global)
                idx_file += 1
                idx_global += 1
                if not member.en:
                    continue
                sig = _member_signature(store, member)
                groups.setdefault(sig, []).append(member)
    result = {sig: members for sig, members in groups.items()
              if len(members) >= 2}
    store._dup_groups = result
    return result


def group_for(store, item):
    """Return the duplicate group (list of :class:`GroupMember`) for ``item``.

    Accepts a full :class:`Item` or a light :class:`ScanItem`/``GroupMember``
    (only ``file``/``key``/``vn`` are read). Returns ``None`` when the row is
    not a member of any group.
    """
    groups = duplicate_groups(store)
    if not groups:
        return None
    member = GroupMember(store, item.file, item.key, item.vn, 0, 0)
    return groups.get(_member_signature(store, member))


def canonical_member(group):
    """First member with a non-empty translation (else the first member).

    The canonical member carries the group's shared VN and its markers are the
    ones shown/edited in the editor; the order follows the row's index in the
    file.
    """
    for m in group:
        if m.vn:
            return m
    return group[0]


def apply_group_edit(store, group, compound):
    """Persist an edited compound string to every member of a duplicate group.

    Reuses :func:`apply_edit` per member, so the translations, highlight
    decisions and overrides (incl. the ``{p}`` player marker) are written for
    each member's own file/key/rids. When any member carries a manual
    ``times_`` override, the group's shared voice-sync state (the merged
    ``times_`` of the first such member) is stamped onto every member so a
    save fully unifies the group; if none has one, ``times_`` is left alone
    (the game default already compares equal everywhere). Returns the
    aggregated warnings.

    Each member's ``vn`` is refreshed from the write so the group index stays
    live: otherwise ``canonical_member``/the duplicate ``✓`` would keep using
    the stale translation captured when the group was first built.
    """
    warnings = []
    # find the member whose times_ override defines the group's shared voice
    # sync, before apply_edit (which never touches times_) rewrites the row
    shared = None
    for m in group:
        if not m.ids:
            continue
        rec = (store.overrides or {}).get(
            m.file[:-len(".msg")], {}).get(m.ids[0], {})
        if rec.get("times_"):
            shared = m
            break
    for m in group:
        item = m.materialize(store)
        warnings += apply_edit(store, item, compound)
        m.vn = item.vn
    if shared is not None:
        base = shared.file[:-len(".msg")]
        times = tuned_times(store, base, shared.ids[0])
        out = {}
        for i, (_t, _w, start, end) in enumerate(times):
            out[str(i)] = [start, end]
        if out:
            for m in group:
                for rid in m.ids:
                    ov = store.overrides.setdefault(base, {}).setdefault(rid, {})
                    ov["times_"] = dict(out)
    return warnings


_WILDCARD_RE = re.compile(r"[\*\?]")
_last_query = None
_last_re = None

# C-level fold for pure-ASCII search keys: lowercase A-Z and map ASCII
# whitespace to a single space. Avoids the two-regex cold path for the English
# reference (100% ASCII), which is the bulk of scan_index normalizations.
_TRANSLATE = str.maketrans(
    {**{i: chr(i + 32) for i in range(ord("A"), ord("Z") + 1)},
     **{ord(c): " " for c in "\t\n\r\f\v"}})

# Vietnamese tone-placement variants: the same word may be typed with the
# tone on the first vowel (old style, e.g. ``hủy``) or on the second vowel
# (new style, e.g. ``huỷ``). Search normalizes both sides to the new-style
# form so ``huỷ diệt`` still matches ``hủy diệt``. Markers here list the
# first-vowel (old) variant mapped to its second-vowel (new) counterpart.
VN_MAP = {
    # uy
    "ủy": "uỷ", "úy": "uý", "ùy": "uỳ", "ũy": "uỹ", "ụy": "uỵ",
    # oe
    "ỏe": "oẻ", "óe": "oé", "òe": "oè", "õe": "oẽ", "ọe": "oẹ",
    # oa
    "ỏa": "oả", "óa": "oá", "òa": "oà", "õa": "oã", "ọa": "oạ",
}
_VN_RE = re.compile("|".join(sorted(VN_MAP, key=len, reverse=True)))


def _vn_fix(m):
    return VN_MAP[m.group(0)]


@functools.lru_cache(maxsize=1 << 18)
def _norm_key(s):
    """Lowercase, collapse whitespace and normalize Vietnamese tone mark
    placement (``uy/oe/oa``) to the new-style second-vowel form.

    The result is the shared search key: the query and every candidate are
    run through the same fold, so ``huỷ diệt`` matches ``hủy diệt``.

    Pure-ASCII keys (the English reference is 100% ASCII) take a C-level
    ``str.translate`` + ``split/join`` path; Vietnamese keys keep the tone
    regex. Edge whitespace is trimmed by ``split/join`` (queries are always
    stripped first, so substring matching is unaffected).
    """
    if s.isascii():
        return " ".join(s.translate(_TRANSLATE).split())
    s = _VN_RE.sub(_vn_fix, s.lower())
    return " ".join(s.split())


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
    for i, tok in enumerate(_WILDCARD_RE.findall(q)):
        out += parts[i] + (".*" if tok == "*" else ".")
    out += parts[-1]
    _last_re = re.compile(out, re.IGNORECASE | re.DOTALL)
    _last_query = q
    return _last_re


def search_hit(store, item, query):
    """Case-insensitive match of ``query`` against original/translation/ids.

    ``*`` and ``?`` act as wildcards (any run / any single character);
    otherwise the match is a plain substring test. Whitespace is normalised on
    both sides (``\\n`` treated like a space) and Vietnamese tone placement is
    normalised to the new-style form, so ``huỷ`` matches ``hủy``. Rows scanned
    from a :class:`ScanRow` carry precomputed normalized keys; anything else
    falls back to on-the-fly normalization.
    """
    if not query:
        return True
    if _WILDCARD_RE.search(query):
        rx = _wildcard_regex(_norm_key(query))
        en = item.en_norm if item.en_norm is not None else _norm_key(item.en)
        vn = item.vn_norm if item.vn_norm is not None else _norm_key(item.vn)
        ids = item.ids_low if item.ids_low is not None else None
        if ids is None:
            ids = [rid.lower() for rid in item.ids]
        return bool(rx.search(en) or rx.search(vn) or any(rx.search(r) for r in ids))
    q = _norm_key(query)
    if q in (item.en_norm if item.en_norm is not None else _norm_key(item.en)):
        return True
    if q in (item.vn_norm if item.vn_norm is not None else _norm_key(item.vn)):
        return True
    ids = item.ids_low if item.ids_low is not None else None
    if ids is None:
        return any(q in rid.lower() for rid in item.ids)
    return any(q in r for r in ids)


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
    except Exception:  # noqa: BLE001 - absent/unshaped tuning defaults to empty
        return []
    out = []
    for rec in entries.values():
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
    except Exception:  # noqa: BLE001 - absent/unshaped tuning defaults to empty
        entries = {}
    out = []
    for rec in entries.values():
        if rec.get("id_") != rid:
            continue
        override = {}
        try:
            override = (store.overrides or {}).get(base, {}).get(rid, {}) \
                .get("times_", {}) or {}
        except Exception:  # noqa: BLE001 - unshaped override ignored
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


def tuned_times_index(store):
    """Return ``{base: {rid: True}}`` for every rid carrying ``times_`` markers.

    Built once (cached on the store) from the tuned tables. ``times_`` is
    rid-keyed, so a rid's subid splits share the same markers. The tuning is
    immutable during a session, so the cache never needs invalidating; the
    overrides side is read live by ``times_state``.
    """
    cache = getattr(store, "_times_index", None)
    if cache is not None:
        return cache
    cache = {}
    for base, entries in ((store.tuned or {}).get("files", {}) or {}).items():
        idx = {}
        for rec in entries.values():
            rid = rec.get("id_")
            if rid and rec.get("times_"):
                idx[rid] = True
        cache[base] = idx
    store._times_index = cache
    return cache


def times_state(store, base, rid):
    """Return the voice-sync (``times_``) state of one row id in a table.

    ``"none"``   -> the rid has no ``times_`` markers in the tuned tables.
    ``"auto"``   -> the rid has ``times_`` but no manual override yet (the
                    game default / auto-applied pacing is in effect).
    ``"edited"`` -> the rid has ``times_`` and a manual override exists in
                    ``tag_overrides.json`` (hand-fixed via the F9 panel).
    """
    if not tuned_times_index(store).get(base, {}).get(rid):
        return "none"
    if (store.overrides or {}).get(base, {}).get(rid, {}).get("times_"):
        return "edited"
    return "auto"


_VIET_PAT = re.compile(r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệ"
                       r"ìíỉĩịòóỏõọôồốổỗộơờớởỡợ"
                       r"ùúủũụưừứửữựỳýỷỹỵđĐ]")
UNTR_PROSE_MIN = 40


def tr_state(vn):
    """Return the translation state of one row's stored value.

    ``"ok"``    -> a real Vietnamese translation is present.
    ``"empty"`` -> nothing stored (blank / whitespace only); the patcher
                   falls back to the English reference for such rows.
    ``"en"``    -> prose-length text (>= ``UNTR_PROSE_MIN`` chars) with no
                   Vietnamese diacritics: an English-looking string that has
                   not been translated yet. Short non-Vietnamese strings
                   (proper nouns, numbers, staff credits) stay ``"ok"``.
    """
    v = (vn or "").strip()
    if not v:
        return "empty"
    if len(v) >= UNTR_PROSE_MIN and not _VIET_PAT.search(v):
        return "en"
    return "ok"


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


def vn_index_to_compound(compound, vn, offset):
    """Map a plain-VN index back to its position in the compound editor string.

    The reverse of :func:`vn_index_at` (same escape/marker conventions: ``\\{``,
    ``\\}``, ``\\\\``, the ``{p}`` player point and ``{c:..}``/``{w:..}``/
    ``{b:..}`` highlight markers). Returns the compound index where the plain-VN
    character at ``offset`` sits, or the end of the compound when past it.
    A highlight phrase may itself contain escaped literals, so an offset inside
    a marker is mapped to the exact character inside the ``{c:...}`` body.
    """
    def _raw_index_of_plain(body, q):
        k = cnt = 0
        while k < len(body) and cnt < q:
            if body[k] == "\\" and k + 1 < len(body) and body[k + 1] in "{}":
                k += 2
            else:
                k += 1
            cnt += 1
        return k

    if not compound:
        return 0
    i = 0          # compound index
    p = 0          # plain-VN index
    n = len(compound)
    while i < n:
        c = compound[i]
        if c == "\\" and i + 1 < n and compound[i + 1] in "{}":
            if p >= offset:
                return i
            p += 1
            i += 2
            continue
        if c == "\\" and i + 1 < n and compound[i + 1] == "\\":
            if p >= offset:
                return i
            p += 1
            i += 2
            continue
        if c == "{":
            if compound.startswith("{p}", i):
                i += 3
                continue
            m = HIGHLIGHT_RE.match(compound, i)
            if m:
                body = m.group(2)
                inner = len(_unesc(body))
                rel = offset - p          # plain char inside the phrase?
                if 0 <= rel < inner:
                    return i + 3 + _raw_index_of_plain(body, rel)
                i += len(m.group(0))
                p += inner
                continue
        if p >= offset:
            return i
        p += 1
        i += 1
    return i


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
        for key, tag in TAG.items():
            for s, e in rec.get(key, []):
                if 0 <= s <= e <= len(en):
                    groups.setdefault((s, e), set()).add(tag)
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
    if item.key in table:
        table[item.key] = vn
    else:
        warnings.append(f"{item.file}: row id not found; text not saved")
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
            if ren.get(k):
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
        __slots__ = ("markers", "player_pos", "speaker", "vn")
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


def self_test(store, file, key):
    """Round-trip an item: build compound, parse it back, assert no change."""
    holds = {}
    item = next((it for it in iter_items(store, bases={file[:-len(".msg")]},
                                        holds=holds)
                 if it.key == key), None)
    if item is None:
        print(f"self-test: item not found: {key}")
        return False
    table = store.tables[file]
    before_vn = table[key]
    base = file[:-len(".msg")]
    before_dec = {r: copy.deepcopy(d)
                  for r, d in store.decisions.get(base, {}).items()}
    before_ov = {r: copy.deepcopy(d)
                 for r, d in store.overrides.get(base, {}).items()}
    compound = build_compound(item)
    _speaker, vn2, _, _ = parse_compound(compound)
    warnings = apply_edit(store, item, compound)
    ok = table[key] == before_vn and not warnings
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