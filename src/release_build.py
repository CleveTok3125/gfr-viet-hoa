"""Release build-VH stamp decorator.

Wraps ``verify.gen_manifest``: before the manifest is written, records the
current build timestamp ``VH vYYYY.MM.DD.HHMM`` into:

- ``meta.build_vh`` of ``translations.json``,
- the in-game version title row (``text_ui.msg``, ``Version {0}``), inserted
  after the version placeholder and separated by ``" - "``.

The wrapped function then reads ``meta.build_vh`` back from the file, so the
release manifest records the same stamp.
"""
import functools
import json
import os
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def vh_stamp(now=None):
    """Current build timestamp, e.g. ``VH v2026.08.09.1015``."""
    return "VH v" + (now or datetime.now()).strftime("%Y.%m.%d.%H%M")


def stamp_release(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        stamp = vh_stamp()
        path = os.path.join(REPO_ROOT, "translations.json")
        with open(path, encoding="utf-8") as fh:
            trans = json.load(fh)
        trans.setdefault("meta", {})["build_vh"] = stamp
        table = trans["translations"].setdefault("text_ui.msg", {})
        table["Version {0}"] = f"Phiên bản {{0}} - {stamp}"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(trans, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        return func(*args, **kwargs)
    return wrapper