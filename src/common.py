"""Shared helpers: vendor bootstrap, game directory detection, data loading."""
import gzip
import hashlib
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR_DIR = os.path.join(REPO_ROOT, "vendor")
DATA_DIR = os.path.join(REPO_ROOT, "data")

TEXT_KO = "data/system/table/text/ko"
SCENARIO_KO = "data/system/table/scenario/ko"


def table_rel(file):
    """Relative game dir holding a given .msg table."""
    return SCENARIO_KO if file.startswith("text_scenario") else TEXT_KO


def bootstrap():
    if VENDOR_DIR not in sys.path:
        sys.path.insert(0, VENDOR_DIR)


def repo_file(name):
    return os.path.join(REPO_ROOT, name)


def load_translations():
    with open(repo_file("translations.json"), encoding="utf-8") as f:
        return json.load(f)


def load_rules():
    with open(repo_file("rules.json"), encoding="utf-8") as f:
        return json.load(f)


def check_version(game_dir, fingerprint=None):
    """Compare the English sources of `game_dir` against the build fingerprint
    stored in translations.json. Returns (ok, mismatches, checked).

    Used to warn that the translation table may not match a newer game build.
    """
    if fingerprint is None:
        fingerprint = load_translations()["meta"].get("build_fingerprint", {})
    if not fingerprint:
        return True, [], 0
    try:
        from extract import extract
    except ImportError:
        return True, [], 0
    mismatches = []
    checked = 0
    for path, expected in fingerprint.items():
        data = extract(game_dir, path)
        checked += 1
        if data is None:
            mismatches.append((path, expected, "<not found>"))
            continue
        actual = hashlib.md5(data).hexdigest()
        if actual != expected:
            mismatches.append((path, expected, actual))
    return not mismatches, mismatches, checked


def load_filelist():
    """Load the internal file-path list (hash -> path mapping).

    Priority:
      1. $GBFR_FILELIST - a plain-text filelist from GBFRDataTools (fresh
         copy for a newer game build)
      2. bundled data/filelist.txt.gz
    """
    path = os.environ.get("GBFR_FILELIST")
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return f.read().splitlines()
    with gzip.open(os.path.join(DATA_DIR, "filelist.txt.gz"), "rt", encoding="utf-8") as f:
        return f.read().splitlines()


# Candidate roots where a GBF Relink install may live.
def _candidate_roots():
    roots = []
    if sys.platform == "win32":
        for letter in "CDEF":
            roots.append(f"{letter}:\\")
    else:
        for base in ("/mnt", "/run/media"):
            try:
                for entry in sorted(os.listdir(base)):
                    roots.append(os.path.join(base, entry))
            except OSError:
                pass
        roots += [
            os.path.expanduser("~/.local/share/Steam/steamapps/common"),
            os.path.expanduser("~/.steam/steam/steamapps/common"),
        ]
    return roots


def find_game_dir():
    """Locate a directory that looks like a GBF Relink install (has data.i
    and the loose text tables). Returns path or None.

    Depth-limited so it never hangs scanning an entire drive (important on
    Windows); the gfrpatch module only uses this as a hint and asks the
    user for the path anyway.
    """
    hint = os.environ.get("GBFR_GAME")
    if hint and os.path.isfile(os.path.join(hint, "data.i")):
        return hint
    skip = {".", "..", "Windows", "Program Files", "Program Files (x86)",
            "Users", "$Recycle.Bin", "System Volume Information", "Recovery",
            "AppData", ".cache", "__pycache__"}
    for root in _candidate_roots():
        for dirpath, dirnames, filenames in os.walk(root):
            depth = dirpath[len(root):].count(os.sep)
            if "data.i" in filenames and dirpath.endswith("Granblue Fantasy - Relink"):
                return dirpath
            if depth >= 8:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d not in skip]
    return None
