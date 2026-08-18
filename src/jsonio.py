"""Drop-in ``json``-compatible reader/writer that prefers orjson when installed.

Mirrors the stdlib ``json`` API (``load`` / ``loads`` / ``dump`` / ``dumps``)
so call sites can import it under the ``json`` alias and read naturally:

    import jsonio as json

orjson is a compiled C backend that only reproduces the stdlib output for a
small set of formatting choices, so the fast path is gated to exactly those
combinations; every other call is delegated to the stdlib so behaviour is
byte-identical everywhere:

- ``loads`` with no keyword arguments
- ``dumps`` with ``indent=2`` (``OPT_INDENT_2`` matches ``json.dumps(indent=2)``)
- ``dumps`` compact (``separators=(",", ":")``) matches orjson's default output

orjson always emits UTF-8, so the fast path implies ``ensure_ascii=False``;
calls relying on the default ``ensure_ascii=True`` or on spaced separators
(``", "``) go through the stdlib. Without orjson installed every call just
falls through to the stdlib, so the module is a safe drop-in either way.
"""
from __future__ import annotations

import json as _json

try:
    import orjson as _orjson
except ImportError:
    _orjson = None

__all__ = ["dump", "dumps", "load", "loads"]


def loads(s, **kwargs):
    if _orjson is not None and not kwargs:
        return _orjson.loads(s)
    if isinstance(s, bytes):  # stdlib json only accepts str
        s = s.decode("utf-8")
    return _json.loads(s, **kwargs)


def load(fp, **kwargs):
    return loads(fp.read(), **kwargs)


def dumps(obj, **kwargs):
    if _orjson is not None:
        if kwargs.get("indent") == 2 \
                and kwargs.get("ensure_ascii") is False \
                and set(kwargs) == {"indent", "ensure_ascii"}:
            return _orjson.dumps(obj, option=_orjson.OPT_INDENT_2).decode("utf-8")
        if kwargs.get("indent") is None \
                and kwargs.get("ensure_ascii") is False \
                and kwargs.get("separators") == (",", ":") \
                and set(kwargs) == {"ensure_ascii", "separators"}:
            return _orjson.dumps(obj).decode("utf-8")
    return _json.dumps(obj, **kwargs)


def dump(obj, fp, **kwargs):
    fp.write(dumps(obj, **kwargs))