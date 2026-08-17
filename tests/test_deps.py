"""Runtime-backend equivalence tests.

The project prefers pip-installed compiled builds (``msgpack`` C, ``xxhash``
C, ``lz4`` C) when they are available and falls back to the vendored
pure-Python copies otherwise (see ``vendor/README.md`` and ``src/deps/``).
The vendored pure copies are the *pinned* reference: these tests assert the
selected backend — the pip build when installed — produces identical results,
so a drift between a pip build and the pinned version is caught on machines
that have pip installed. Uses real repo data, no game install.
"""
import os
import sys
import unittest
from importlib import machinery, util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "vendor")):
    if p not in sys.path:
        sys.path.insert(0, p)

VENDOR = os.path.join(ROOT, "vendor")

# A raw LZ4 block (no size header — the game stores the decompressed size in
# the chunk metadata) compressed by the compiled ``lz4`` library, plus its
# expected plaintext. Verifies the selected backend and the pure fallback
# decode the same wire bytes identically.
LZ4_FIXTURE = bytes.fromhex(
    "f00e4772616e626c75652046616e746173793a2052656c696e6b20e28093"
    "201d00f1042064c3a9636f75767265206c65206369656c2e18000f35004e5069656c2e20")
LZ4_PLAINTEXT = (
    "Granblue Fantasy: Relink \u2013 Gran d\u00e9couvre le ciel. " * 3).encode()

MSGPAYLOADS = [
    None, True, False, 0, 1, -1, 2 ** 31, -2 ** 31, 2 ** 63, -2 ** 63,
    2 ** 64 - 1, 3.5, -0.0, 1e300, "",
    "Granblue Fantasy", "h\u00e9llo vi\u1ec7t \u2728\n\u2026",
    b"", b"\x00\xffbinary",
    [1, "a", None, {"x": [1.5, b"b"]}],
    {"a": 1, "vi\u1ec7t": {"nested": [True, None]}, "b": b"bytes",
     "c": [1.0, 2]},
]


def _load_pip_package(name):
    """Import ``name`` from site-packages, bypassing the vendored copy.

    Temporarily swaps the (possibly already-imported) vendored copy out of
    ``sys.modules`` so the pip package's relative submodule imports resolve
    to site-packages, then restores the vendored copy afterwards.
    """
    saved = {k: mod for k, mod in sys.modules.items()
             if k == name or k.startswith(name + ".")}
    for k in saved:
        del sys.modules[k]
    try:
        paths = [p for p in sys.path
                 if os.path.realpath(p) != os.path.realpath(VENDOR)]
        spec = machinery.PathFinder.find_spec(name, paths)
        assert spec is not None
        assert spec.loader is not None
        mod = util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.modules.update(saved)


def _load_module_package(name, base, asname):
    """Load package ``name`` from ``base``, registered in sys.modules as ``asname``."""
    root = os.path.join(base, name)
    spec = util.spec_from_file_location(
        asname, os.path.join(root, "__init__.py"),
        submodule_search_locations=[root])
    assert spec is not None
    assert spec.loader is not None
    mod = util.module_from_spec(spec)
    sys.modules[asname] = mod
    spec.loader.exec_module(mod)
    return mod


class MsgpackBackendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.pip = _load_pip_package("msgpack")
        except ImportError:
            cls.pip = None
        cls.pin = _load_module_package("msgpack", VENDOR, "msgpack_pin")

    def test_pip_matches_pinned_wire_format(self):
        if self.pip is None:
            self.skipTest("pip msgpack not installed")
        for x in MSGPAYLOADS:
            self.assertEqual(self.pip.packb(x), self.pin.packb(x), repr(x))

    def test_cross_unpack_agrees(self):
        if self.pip is None:
            self.skipTest("pip msgpack not installed")
        for x in MSGPAYLOADS:
            self.assertEqual(self.pip.unpackb(self.pin.packb(x)), x, repr(x))
            self.assertEqual(self.pin.unpackb(self.pip.packb(x)), x, repr(x))


class Xxh64BackendTest(unittest.TestCase):
    SEEDS = (0, 1, 42, 0x9E3779B1)
    SAMPLES = (
        "", "a", "abc", "abcde", "h\u00e9llo vi\u1ec7t \u2728",
        "data/system/table/text/ko/text_ui.msg",
        ("ui/campaign/gra/skill_skillinventory_01/campaign/kor/"
         "skill_skillinventory_01_t.tex"),
        b"\x00\x01\x02" * 17, b"\xff" * 31, b"\xff" * 32,
        "x" * 33, "x" * 64, "x" * 100, "x" * 1000,
    )

    def setUp(self):
        from xxh64_pure import xxh64 as pin  # pyright: ignore[reportMissingImports]

        from deps.xxh64 import xxh64 as sel
        self.sel, self.pin = sel, pin

    def test_agrees_with_pinned_pure(self):
        for seed in self.SEEDS:
            for s in self.SAMPLES:
                self.assertEqual(self.sel(s, seed), self.pin(s, seed),
                                 (seed, s))

    def test_known_reference_vectors(self):
        self.assertEqual(self.sel(b""), 0xEF46DB3751D8E999)
        self.assertEqual(self.sel(b"a"), 0xD24EC4F1A98C6E5B)
        self.assertEqual(self.sel(b"abc"), 0x44BC2CF5AD770999)

    def test_digest_is_xxh64_when_compiled(self):
        from deps.xxh64 import _COMPILED, digest
        if not _COMPILED:
            self.skipTest("compiled xxhash not installed")
        blob = os.urandom(1 << 16)
        self.assertEqual(digest(blob), self.sel(blob))


class Lz4BlockBackendTest(unittest.TestCase):
    def setUp(self):
        from lz4_block_pure import (
            decompress as pin,  # pyright: ignore[reportMissingImports]
        )

        from deps.lz4_block import decompress as sel
        self.sel, self.pin = sel, pin

    def test_fixture_agrees_with_pinned_pure(self):
        self.assertEqual(self.sel(LZ4_FIXTURE, len(LZ4_PLAINTEXT)),
                         LZ4_PLAINTEXT)
        self.assertEqual(self.pin(LZ4_FIXTURE, len(LZ4_PLAINTEXT)),
                         LZ4_PLAINTEXT)

    def test_pip_compressed_block_decodes_with_both(self):
        try:
            from lz4.block import compress
        except ImportError:
            self.skipTest("pip lz4 not installed")
        text = ("C\u1eadu b\u00e9 v\u00e0 con r\u1ed3ng th\u1ea7n l\u1eeda \u2014 "
                "Granblue Fantasy: Relink. " * 40).encode()
        block = compress(text, store_size=False)
        self.assertEqual(self.sel(block, len(text)), text)
        self.assertEqual(self.pin(block, len(text)), text)


class FlatbuffersBackendTest(unittest.TestCase):
    def test_pin_guard_keeps_the_pinned_version(self):
        from common import FLATBUFFERS_PIN, bootstrap
        bootstrap()
        import flatbuffers
        self.assertEqual(flatbuffers.__version__, FLATBUFFERS_PIN)

    def test_gbfr_schema_roundtrip(self):
        from flatbuffers import Builder

        from gbfr_schema import IndexFile
        builder = Builder(0)
        vec = IndexFile.IndexFileCreateArchiveFileHashesVector(builder,
                                                               [1, 2, 3])
        IndexFile.IndexFileStart(builder)
        IndexFile.IndexFileAddArchiveFileHashes(builder, vec)
        off = IndexFile.IndexFileEnd(builder)
        builder.Finish(off)
        root = IndexFile.IndexFile.GetRootAs(builder.Output(), 0)
        self.assertEqual(
            [root.ArchiveFileHashes(i)
             for i in range(root.ArchiveFileHashesLength())],
            [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
