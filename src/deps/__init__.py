"""Compiled-first wrappers for third-party runtime dependencies.

The project prefers pip-installed compiled builds (``msgpack`` C, ``xxhash``
C, ``lz4`` C) when they are available and falls back to the vendored
pure-Python copies in ``vendor/`` otherwise. ``msgpack`` and ``flatbuffers``
are selected purely by ``sys.path`` order in :func:`common.bootstrap`
(``vendor/`` is appended, so pip wins); ``xxh64`` and ``lz4_block`` need
wrappers because the project's own fallbacks live under different names than
the pip packages they replace.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, "..")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common import bootstrap

bootstrap()
