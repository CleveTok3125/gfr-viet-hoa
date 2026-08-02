"""Read the game version from the Granblue Fantasy: Relink executable.

Extracts the "FileVersion" string from the PE version resource. A direct
UTF-16 scan for the version keys is used first (robust even when the PE
resource directory does not map cleanly, e.g. packed/redistributed exes);
a full PE resource-directory walk is kept as a secondary path.
"""
import os


def _utf16_find(data, text):
    return data.find(text.encode("utf-16-le"))


def _heuristic_version(data):
    """Find 'FileVersion' / 'ProductVersion' by scanning the UTF-16 blob."""
    for key in ("FileVersion", "ProductVersion"):
        idx = _utf16_find(data, key)
        if idx < 0:
            continue
        tail = data[idx + len(key.encode("utf-16-le")):]
        tail = tail.lstrip(b"\x00")
        text = tail.decode("utf-16-le", "ignore")
        value = text.split("\x00")[0].strip()
        if value:
            return value
    return None


def game_version(exe_path):
    """Return the game version string from the executable, or None."""
    if not exe_path or not os.path.isfile(exe_path):
        return None
    try:
        with open(exe_path, "rb") as f:
            data = f.read()
        return _heuristic_version(data)
    except Exception:
        return None
