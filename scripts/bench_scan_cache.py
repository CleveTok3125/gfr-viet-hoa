#!/usr/bin/env python3
"""Benchmark the persistent scan-index cache (Store + .scan_index.cache.json).

Usage:
    python3 scripts/bench_scan_cache.py [GAME_DIR]

GAME_DIR defaults to $GBFR_GAME or the auto-detected install. Runs three
passes with a throwaway cache file:

  1. cold:  cache removed first    - classic first-boot cost
  2. warm:  cache present, fresh Store - typical next-boot cost
  3. warm2: same again, to confirm stability

Each pass reports wall time plus Store cache hits/misses: hits are tables
served from the cache, skipping the game's LZ4 + msgpack decode entirely.
"""
import argparse
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "vendor")):
    if p not in sys.path:
        sys.path.insert(0, p)

from common import find_game_dir, load_translations
from tr_edit_core import Store


def run_pass(game_dir, cache_path):
    t0 = time.perf_counter()
    store = Store(game_dir=game_dir, use_cache=True, cache_path=cache_path)
    store.scan_index()
    elapsed = time.perf_counter() - t0
    return elapsed, store.cache_hits, store.cache_misses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_dir", nargs="?", default=None,
                        help="GBF Relink install dir "
                             "(default: $GBFR_GAME or auto-detected)")
    args = parser.parse_args()
    game_dir = args.game_dir or os.environ.get("GBFR_GAME") or find_game_dir()
    if not game_dir or not os.path.isfile(os.path.join(game_dir, "data.i")):
        sys.exit(f"game install not found: {game_dir!r} "
                 "(pass GAME_DIR or set GBFR_GAME)")
    print(f"game : {game_dir}")
    tables = load_translations().get("translations", {})
    print(f"rows : {sum(len(t) for t in tables.values()):,} across "
          f"{len(tables)} tables")

    with tempfile.TemporaryDirectory() as tmp:
        cache_path = os.path.join(tmp, ".scan_index.cache.json")
        for name, reset in (("cold ", True), ("warm ", False), ("warm2", False)):
            if reset and os.path.isfile(cache_path):
                os.remove(cache_path)
            elapsed, hits, misses = run_pass(game_dir, cache_path)
            size = (os.path.getsize(cache_path) / 1048576
                    if os.path.isfile(cache_path) else 0.0)
            print(f"{name}: {elapsed:6.2f}s   hits={hits:>3} "
                  f"misses={misses:>3}   cache_file={size:.1f} MB")


if __name__ == "__main__":
    main()
