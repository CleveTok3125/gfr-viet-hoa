"""Realign the newline structure of a Vietnamese translation so it matches
the line layout of the original English string.

The game renders each `\\n`-separated line with its own colour / typewriter
pacing and does NOT auto-wrap, so a translation that inserts or drops
newlines arbitrarily causes mis-highlighted text, broken wrapping and
out-of-sync dialog playback.

Strategy: flatten the Vietnamese text (keeping `<d>` tags and {n}
placeholders intact since they contain no spaces) and re-split it into the
same number of lines as the English source, with each line's length
proportional to the English line it corresponds to. Empty English lines
(paragraph breaks) are preserved as empty lines.

A second pass then splits any line longer than `max_line` (the game text box
is roughly 90-110 characters wide) so long Vietnamese sentences do not
overflow the box.
"""

DEFAULT_MAX_LINE = 90


def _snap_to_space(text, pos, start, end):
    """Find the whitespace index closest to `pos` within [start, end].
    Returns pos itself if no whitespace is available in the window.
    """
    window = 30
    lo = max(start, pos - window)
    hi = min(end, len(text) - 1)
    best = None
    best_dist = None
    for i in range(lo, hi + 1):
        if text[i] in " \t":
            d = abs(i - pos)
            if best_dist is None or d < best_dist:
                best = i
                best_dist = d
    return best if best is not None else pos


def realign(en, vn, max_line=DEFAULT_MAX_LINE):
    """Return (new_vn, changed). If the newline count already matches and no
    line is too long, the Vietnamese text is returned untouched."""
    if en.count("\n") == vn.count("\n"):
        if all(len(line) <= max_line for line in vn.split("\n")):
            return vn, False
        new_vn = _split_long_lines(vn, max_line)
        return new_vn, new_vn != vn

    en_lines = en.split("\n")
    target = len(en_lines)
    if target <= 1:
        return vn, False

    widths = [len(line) for line in en_lines]
    total = sum(widths)
    if total == 0:
        return vn, False

    flat = " ".join(seg.strip() for seg in vn.split("\n") if seg.strip())
    flat_len = len(flat)
    if flat_len == 0:
        return vn, False

    out = []
    cursor = 0
    for w in widths:
        if w == 0:
            out.append("")
            continue
        if cursor >= flat_len:
            out.append("")
            continue
        want = max(1, round(w / total * flat_len))
        end = min(cursor + want, flat_len)
        if end < flat_len:
            end = _snap_to_space(flat, end, cursor, flat_len)
        segment = flat[cursor:end].strip()
        if not segment:
            break
        out.append(segment)
        cursor = end
        if cursor < flat_len and flat[cursor] in " \t":
            cursor += 1

    if cursor < flat_len:
        rest = flat[cursor:].strip()
        if rest:
            if out and out[-1]:
                out[-1] += " " + rest
            else:
                out.append(rest)

    while len(out) < target:
        out.append("")
    if len(out) > target:
        out = out[:target]

    new_vn = _split_long_lines("\n".join(out), max_line)
    return new_vn, new_vn != vn


def _split_long_lines(text, max_line):
    """Split lines longer than max_line at the nearest space to the middle."""
    lines = text.split("\n")
    out = []
    for line in lines:
        while len(line) > max_line:
            mid = len(line) // 2
            lo = max(0, mid - max_line // 2)
            hi = min(len(line), max_line)
            candidates = [
                i for i in range(lo, hi) if line[i] == " "
            ]
            split_at = min(candidates, key=lambda i: abs(i - mid)) if candidates else -1
            if split_at < 0:
                split_at = mid
            out.append(line[:split_at].strip())
            line = line[split_at:].strip()
            if not line:
                break
        out.append(line)
    return "\n".join(out)
