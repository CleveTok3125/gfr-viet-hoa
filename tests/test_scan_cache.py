"""Tests for the persistent scan-index cache (``ScanCache`` + ``Store``).

The editor build extracts every English table from the game (LZ4 + msgpack);
the cache persists those maps keyed by an xxh64 of the archive chunk they came
from, so a later boot serves them from a JSON file instead. These tests cover
the cache round-trip, its digest invalidation, and the ``Store.id_text_map``
hit/miss wiring (game extraction mocked — no game install needed).
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "vendor")):
    if p not in sys.path:
        sys.path.insert(0, p)

import msgpack

from tr_edit_core import ScanCache, Store

DIGEST_A = 0xDEADBEEF12345678
DIGEST_B = 0x12345678DEADBEEF

# An EN table payload matching what ``id_text_map`` decodes from the game.
MOCK_TABLE = msgpack.packb({
    "rows_": [
        {"column_": {"id_hash_": "H1", "subid_hash_": "", "text_": "Alpha"}},
        {"column_": {"id_hash_": "H2", "subid_hash_": "S2",
                     "text_": "Beta"}},
    ],
})


class ScanCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, ".scan_index.cache.json")
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_roundtrip_persists(self):
        cache = ScanCache(path=self.path, game_dir="/game")
        cache.put("text_ui.msg", DIGEST_A, {"H1": "Alpha"})
        cache.save()
        self.assertTrue(os.path.isfile(self.path))
        again = ScanCache(path=self.path, game_dir="/game")
        self.assertEqual(again.get("text_ui.msg", DIGEST_A), {"H1": "Alpha"})
        self.assertIsNone(again.get("other.msg", DIGEST_A))

    def test_digest_mismatch_invalidates_entry(self):
        cache = ScanCache(path=self.path, game_dir="/game")
        cache.put("text_ui.msg", DIGEST_A, {"H1": "Alpha"})
        cache.save()
        again = ScanCache(path=self.path, game_dir="/game")
        self.assertIsNone(again.get("text_ui.msg", DIGEST_B))

    def test_different_game_dir_discards_cache(self):
        cache = ScanCache(path=self.path, game_dir="/gameA")
        cache.put("text_ui.msg", DIGEST_A, {"H1": "Alpha"})
        cache.save()
        again = ScanCache(path=self.path, game_dir="/gameB")
        self.assertEqual(again.tables, {})

    def test_save_is_noop_when_clean(self):
        cache = ScanCache(path=self.path, game_dir="/game")
        cache.save()
        self.assertFalse(os.path.isfile(self.path))

    def test_missing_or_corrupt_file_yields_empty(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": 99}, fh)
        cache = ScanCache(path=self.path, game_dir="/game")
        self.assertEqual(cache.tables, {})
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        cache = ScanCache(path=self.path, game_dir="/game")
        self.assertEqual(cache.tables, {})

    def test_loads_legacy_plain_json(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "game_dir": "/game",
                       "tables": {"text_ui.msg": {"digest": DIGEST_A,
                                                  "id_text": {"H1": "Alpha"}}}},
                      fh)
        cache = ScanCache(path=self.path, game_dir="/game")
        self.assertEqual(cache.get("text_ui.msg", DIGEST_A), {"H1": "Alpha"})


class StoreCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, ".scan_index.cache.json")
        self.addCleanup(shutil.rmtree, self.tmp)

    def _store(self):
        return Store(game_dir="/fake", use_cache=True, cache_path=self.path)

    def test_miss_extracts_and_persists(self):
        with mock.patch("extract.chunk_digest", return_value=DIGEST_A), \
                mock.patch("extract.extract", return_value=MOCK_TABLE):
            store = self._store()
            m = store.id_text_map("text_ui.msg")
            store.cache.save()
        self.assertEqual(m, {"H1": "Alpha", "H2::S2": "Beta"})
        self.assertEqual(store.cache_hits, 0)
        self.assertEqual(store.cache_misses, 1)
        self.assertTrue(os.path.isfile(self.path))

    def test_hit_skips_extraction(self):
        with mock.patch("extract.chunk_digest", return_value=DIGEST_A), \
                mock.patch("extract.extract", return_value=MOCK_TABLE):
            first = self._store()
            first.id_text_map("text_ui.msg")
            first.cache.save()
        with mock.patch("extract.chunk_digest", return_value=DIGEST_A), \
                mock.patch("extract.extract") as extract:
            store = self._store()
            m = store.id_text_map("text_ui.msg")
        self.assertEqual(m, {"H1": "Alpha", "H2::S2": "Beta"})
        self.assertEqual(store.cache_hits, 1)
        self.assertEqual(store.cache_misses, 0)
        extract.assert_not_called()

    def test_digest_change_ignores_stale_entry(self):
        with mock.patch("extract.chunk_digest", return_value=DIGEST_A), \
                mock.patch("extract.extract", return_value=MOCK_TABLE):
            first = self._store()
            first.id_text_map("text_ui.msg")
            first.cache.save()
        with mock.patch("extract.chunk_digest", return_value=DIGEST_B), \
                mock.patch("extract.extract", return_value=MOCK_TABLE) as extract:
            store = self._store()
            store.id_text_map("text_ui.msg")
        self.assertEqual(store.cache_misses, 1)
        extract.assert_called_once()

    def test_scan_index_reports_cache_phase(self):
        with mock.patch("extract.chunk_digest", return_value=DIGEST_A), \
                mock.patch("extract.extract", return_value=MOCK_TABLE):
            self._store().scan_index()
        events = []
        with mock.patch("extract.chunk_digest", return_value=DIGEST_A), \
                mock.patch("extract.extract") as extract:
            self._store().scan_index(
                lambda f, d, t, phase, s: events.append(phase))
        self.assertIn("cache", events)
        self.assertNotIn("normalize", events)
        extract.assert_not_called()


if __name__ == "__main__":
    unittest.main()
