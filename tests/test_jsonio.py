"""Drop-in ``json``-alias equivalence tests for :mod:`jsonio`.

``src/jsonio.py`` mirrors the stdlib ``json`` API and prefers a pip-installed
``orjson`` on a narrow set of formatting choices; every other call delegates
to the stdlib. These tests pin the byte-stability contract: the selected
backend (orjson when installed) must produce output identical to the stdlib
``json`` for the combinations the project uses, and the fallback paths must
be indistinguishable from the stdlib. No game install needed.
"""
import io
import json
import os
import sys
import unittest
from typing import ClassVar

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import jsonio

SAMPLE = {
    "meta": {"build": "2.0.3", "build_vh": "vn-1.2.3"},
    "rows": [
        {"id": "abc123", "vn": "Chào bạn", "flags": [1, 2, 3]},
        {"id": "def456", "vn": "Cảm ơn đã chơi", "flags": []},
    ],
    "ok": True,
    "nada": None,
}


class JsonioEquivalence(unittest.TestCase):
    """orjson fast paths (when installed) match stdlib byte-for-byte."""

    def test_loads_matches_stdlib(self):
        for payload in (SAMPLE, [1, "x"], {"a": "việt"}):
            raw = json.dumps(payload, ensure_ascii=False)
            self.assertEqual(jsonio.loads(raw), json.loads(raw))
            self.assertEqual(jsonio.loads(raw.encode("utf-8")),
                             json.loads(raw))

    def test_indent2_byte_identical(self):
        a = jsonio.dumps(SAMPLE, ensure_ascii=False, indent=2)
        b = json.dumps(SAMPLE, ensure_ascii=False, indent=2)
        self.assertEqual(a, b)

    def test_compact_byte_identical(self):
        a = jsonio.dumps(SAMPLE, ensure_ascii=False, separators=(",", ":"))
        b = json.dumps(SAMPLE, ensure_ascii=False, separators=(",", ":"))
        self.assertEqual(a, b)

    def test_roundtrip(self):
        for raw in (jsonio.dumps(SAMPLE, ensure_ascii=False, indent=2),
                    jsonio.dumps(SAMPLE, ensure_ascii=False,
                                 separators=(",", ":"))):
            self.assertEqual(jsonio.loads(raw), SAMPLE)

    def test_load_and_dump_helpers(self):
        raw = json.dumps(SAMPLE, ensure_ascii=False)
        self.assertEqual(jsonio.load(io.StringIO(raw)), SAMPLE)
        buf = io.StringIO()
        jsonio.dump(SAMPLE, buf, ensure_ascii=False, indent=2)
        self.assertEqual(buf.getvalue(),
                         json.dumps(SAMPLE, ensure_ascii=False, indent=2))


class JsonioFallback(unittest.TestCase):
    """Calls outside the fast path stay byte-identical to the stdlib."""

    def test_default_separators(self):
        self.assertEqual(jsonio.dumps(SAMPLE),
                         json.dumps(SAMPLE))

    def test_ascii_escape_default(self):
        self.assertEqual(jsonio.dumps(SAMPLE, ensure_ascii=True),
                         json.dumps(SAMPLE, ensure_ascii=True))

    def test_spaced_default_with_utf8(self):
        # ensure_ascii=False without indent/separators uses stdlib ", " spacing
        self.assertEqual(jsonio.dumps(SAMPLE, ensure_ascii=False),
                         json.dumps(SAMPLE, ensure_ascii=False))

    def test_sort_keys(self):
        self.assertEqual(jsonio.dumps(SAMPLE, sort_keys=True),
                         json.dumps(SAMPLE, sort_keys=True))

    def test_other_indent(self):
        for n in (0, 4):
            self.assertEqual(
                jsonio.dumps(SAMPLE, ensure_ascii=False, indent=n),
                json.dumps(SAMPLE, ensure_ascii=False, indent=n))

    def test_loads_with_kwargs(self):
        raw = '{"a": 1, "b": 2}'
        self.assertEqual(jsonio.loads(raw, parse_int=float),
                         json.loads(raw, parse_int=float))

    def test_noncompact_separators(self):
        a = jsonio.dumps(SAMPLE, ensure_ascii=False, separators=(";", "="))
        b = json.dumps(SAMPLE, ensure_ascii=False, separators=(";", "="))
        self.assertEqual(a, b)


class JsonioCommittedFiles(unittest.TestCase):
    """The authoring JSONs are byte-stable under the save path.

    Re-dumping any committed file with the project's writer combination
    (``ensure_ascii=False, indent=2`` plus each file's trailing-newline
    convention) must reproduce the committed bytes exactly — so an editor or
    script save never produces a spurious diff.
    """

    FILES: ClassVar[list] = [
        ("translations.json", True),
        ("highlight_decisions.json", False),
        ("tag_overrides.json", False),
        ("tag_tuning.json", False),
        ("data/scenario_speakers.json", False),
        ("data/release_manifest.json", False),
    ]

    def test_authoring_files_reproduce_bytes(self):
        for rel, has_nl in self.FILES:
            path = os.path.join(ROOT, rel)
            with self.subTest(rel=rel):
                with open(path, "rb") as fh:
                    raw = fh.read()
                self.assertEqual(raw.endswith(b"\n"), has_nl, rel)
                data = jsonio.loads(raw)
                out = jsonio.dumps(data, ensure_ascii=False, indent=2)
                if has_nl:
                    out += "\n"
                self.assertEqual(out.encode("utf-8"), raw, rel)


if __name__ == "__main__":
    unittest.main()