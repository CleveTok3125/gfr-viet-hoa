#!/usr/bin/env python3
"""TUI for editing the Vietnamese translations + highlight markers.

A full-screen editor built on `textual`. The editable text is a *compound
string*: the VN translation with marker tokens inline (see tr_edit_core for
the marker convention). Saving writes the parsed result back to
translations.json, highlight_decisions.json and tag_overrides.json.

Usage:
    python3 -m src.tr_edit [--game <dir>] [--file <base>]

Keys:
    Up/Down (or j/k)  move between items
    Ctrl+E            focus the editor
    Ctrl+S            save the current edit (write back to all JSONs)
    Ctrl+R            discard current edit, reload from disk state
    Ctrl+F            focus search box (EN/VN/ID, case-insensitive)
    Ctrl+L            focus file filter (table basename)
    Ctrl+N            next table file
    Ctrl+T/J/G/O  copy VN / JA / EN / compound
    Ctrl+M        copy just the file or just the ID (inline menu)
    Ctrl+H        full debug dump
    F2                configure a regex search & replace rule (inline panel)
    F5                apply the F2 rule to the current item's text
    F9                edit voice-sync (times_) markers for the current item
    Ctrl+Up / Ctrl+Down  previous / next item
    F8                view context (fill range box around the item + jump)
    Esc               back to the item list
    Ctrl+Q            quit
"""
from __future__ import annotations

import argparse
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, ".."))

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.suggester import Suggester
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Static,
    TextArea,
)

from common import bootstrap

bootstrap()

from typing import ClassVar

from tr_edit_core import (
    ScanItem,
    Store,
    apply_edit,
    build_compound,
    iter_scan,
    matches,
    parse_compound,
)

MAX_ROWS = 3000
CONTEXT_MARGIN = 15

LEGEND = (
    "[b]Marker legend[/b]\n"
    "\\[[Speaker]]   speaker prefix (read-only, scenario only)\n"
    "{c:phrase}     colors_ highlight\n"
    "{w:phrase}     words_ highlight\n"
    "{b:phrase}     bolds_ highlight\n"
    "{cw:phrase}    colors_+words_ on the same phrase\n"
    "{p}            player-name insertion point\n"
    "\n"
    "[b]Escapes[/b]  \\{  \\}  \\\\  to show a literal brace / backslash\n"
    "[b]Save[/b]     Ctrl+S writes translations / decisions / overrides\n"
    "[b]Speaker[/b]  auto-prefix; edit text without it, it is re-added\n"
    "\n"
    "[b]Copy[/b]\n"
    "Ctrl+T   plain VN (markers stripped)\n"
    "Ctrl+J   raw Japanese (source for kanji / exact meaning)\n"
    "Ctrl+G   EN (original text)\n"
    "Ctrl+O   compound as in the editor (with markers)\n"
    "Ctrl+M   copy just the file or just the ID (pick in the inline menu)\n"
    "Ctrl+H   full debug dump (ids, speaker, markers, decisions/overrides)\n"
    "\n"
    "[b]Preview[/b]\n"
    "F4        toggle EN preview: plain or with game highlight markers\n"
    "          ({c:}/{w:}/{b:} + {p} player-name insertion point)\n"
    "PgUp/PgDn scroll the focused preview / legend panel\n"
    "Ctrl+F    search (EN / VN / ID; * ? wildcards; \\n = space)\n"
    "Ctrl+L    focus file filter; Tab moves through search/range/file/ID/Speaker\n"
    "ID / Speaker  filter boxes; range holds e.g. N-N (index window)\n"
    "Esc       clear all filters (search/ID/Speaker/file/range)\n"
    "F2        configure a regex search & replace rule (session)\n"
    "F5        apply the F2 rule to the current item's text\n"
    "F9        edit voice-sync (times_) markers for the current item\n"
    "Ctrl+Up/Down  previous / next item\n"
    "F8        view context: fill the file + a small index-range window\n"
    "          around the current item and jump to its row (kept visible)\n"
    "\n"
    "[b]Editor[/b]\n"
    "F3        auto-wrap current text to the EN wrap width\n"
    "          (joins all lines, re-wraps; markers never split)"
)


class ReplacePanel(Vertical):
    """Inline panel (hosted in #inline_panel): configure a regex replace rule.

    Lives inside the app's bottom-left slot instead of a modal screen, so the
    rest of the UI stays usable (you can switch items while it is open). The
    rule is stored on the app (``replace_rule``); F5 applies it to the current
    editor text.
    """

    def __init__(self, app):
        super().__init__(id="replace_panel")
        self.app_ref = app

    def compose(self) -> ComposeResult:
        yield Static("[b]Search & replace rule (session)[/b]",
                     id="replace-title")
        yield Label("Pattern (regex)")
        yield Input(placeholder=r"e.g. tàu bay|thuyền trưởng",
                    id="replace_pattern")
        yield Label("Replacement")
        yield Input(placeholder=r"e.g. phi thuyền", id="replace_repl")
        with Vertical(id="replace-grid"):
            with Horizontal(classes="replace-row"):
                yield Checkbox("Match case", id="replace_case")
                yield Static("", classes="replace-fill")
                yield Button("Close", id="replace_close")
            with Horizontal(classes="replace-row"):
                yield Checkbox("Whole word", id="replace_word")
                yield Static("", classes="replace-fill")
                yield Button("Save", id="replace_do", variant="primary")
        yield Static("-", id="replace_count")
        yield Static("", id="replace_preview")
        yield Static("Saved for this session. Press F5 while editing any "
                     "item to apply it to the current text (Ctrl+S saves "
                     "the result).", classes="replace-sub")

    def on_mount(self) -> None:
        app = self.app_ref
        rx = getattr(app, "replace_rule", None)
        if rx is not None:
            self.query_one("#replace_pattern", Input).value = rx.get("pattern", "")
            self.query_one("#replace_repl", Input).value = rx.get("repl", "")
            self.query_one("#replace_case", Checkbox).value = rx.get("case", False)
            self.query_one("#replace_word", Checkbox).value = rx.get("word", False)
        self.query_one("#replace_pattern", Input).focus()
        self.count()

    @on(Input.Changed, "#replace_pattern")
    @on(Input.Changed, "#replace_repl")
    @on(Checkbox.Changed)
    def _on_input_change(self, event) -> None:
        self.count()

    def _compile(self):
        pat = self.query_one("#replace_pattern", Input).value
        if not pat:
            return None
        flags = 0
        if not self.query_one("#replace_case", Checkbox).value:
            flags |= re.IGNORECASE
        if self.query_one("#replace_word", Checkbox).value:
            pat = r"\b(?:" + pat + r")\b"
        try:
            return re.compile(pat, flags)
        except re.error:
            return None

    def _current_compound(self):
        app = self.app_ref
        if app.current_item is None:
            return None
        return app.query_one("#editor", TextArea).text

    def count(self) -> None:
        rx = self._compile()
        compound = self._current_compound()
        if rx is None or compound is None:
            self.query_one("#replace_count", Static).update(
                "invalid regex" if rx is None else "no item selected")
            self.query_one("#replace_preview", Static).update("")
            return
        from tr_edit_core import parse_compound, replace_in_compound
        _spk, vn, _hl, _pp = parse_compound(compound)
        n = len(rx.findall(vn))
        label = self.query_one("#replace_count", Static)
        prev = self.query_one("#replace_preview", Static)
        label.update(f"{n} match(es) in the current item")
        if n:
            repl = self.query_one("#replace_repl", Input).value
            try:
                result, _subs, _warns = replace_in_compound(compound, rx, repl)
            except re.error:
                prev.update("invalid replacement")
                return
            prev.update(result)
        else:
            prev.update("")

    def action_close(self) -> None:
        self.app_ref.close_slot()

    @on(Button.Pressed)
    def _on_button(self, event: Button.Pressed) -> None:
        if event.button.id == "replace_close":
            self.action_close()
        elif event.button.id == "replace_do":
            self._save_rule()

    @on(Input.Submitted, "#replace_pattern")
    def _on_pattern_submit(self, _event) -> None:
        self.query_one("#replace_repl", Input).focus()

    @on(Input.Submitted, "#replace_repl")
    def _on_repl_submit(self, _event) -> None:
        self._save_rule()

    def _save_rule(self) -> None:
        app = self.app_ref
        rx = self._compile()
        if rx is None:
            self.notify("Pattern is empty or not a valid regex",
                        severity="warning")
            return
        repl = self.query_one("#replace_repl", Input).value
        app.replace_rule = {
            "rx": rx,
            "repl": repl,
            "pattern": self.query_one("#replace_pattern", Input).value,
            "case": self.query_one("#replace_case", Checkbox).value,
            "word": self.query_one("#replace_word", Checkbox).value,
        }
        self.notify("Replace rule saved - press F5 to apply")
        self.app_ref.close_slot()


class TimesPanel(Vertical):
    """Inline panel: view / adjust the item's ``times_`` voice-sync markers.

    Hosted in the bottom-left slot like ReplacePanel. Each marker is shown as a
    row with an editable ``offset`` input (the character *after* the pause: the
    engine pauses right before it, showing everything up to ``offset - 1``);
    ``time`` / ``wait`` are read-only reference. Saving writes the offsets to
    tag_overrides.json (key ``times_``), which
    ``tag_tuning.write_to_game`` stamps onto the tuned tag at patch time.
    """

    def __init__(self, app, markers, rids):
        super().__init__(id="times_panel")
        self.app_ref = app
        self.rids = rids
        self.markers = list(markers)

    def compose(self) -> ComposeResult:
        yield Static(f"[b]Voice-sync[/b] ({', '.join(self.rids)})  [dim]Save auto[/dim]",
                     id="times-title")
        with ScrollableContainer(id="times-scroll"):
            for i, (time, wait, start, end) in enumerate(self.markers):
                with Horizontal(classes="times-row"):
                    yield Input(str(start), id=f"times_off_{i}")
                    yield Static(f"[@time {time:.2f}s{' wait' if wait else ''}]",
                                 classes="times-meta")
        with Horizontal(id="times-actions"):
            yield Button("Cancel", id="times_cancel")
            yield Button("Save", id="times_do", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#times_off_0", Input).focus()
        self.app_ref._schedule_sync_highlight()

    def markers_from_inputs(self) -> list:
        """Current ``(time, wait, start, end)`` from the offset inputs.

        ``time``/``wait`` stay as the tuned reference; ``start`` is the live
        input value (``end`` mirrors it, matching the saved ``[off, off]``).
        """
        out = []
        for i, (time, wait, _start, _end) in enumerate(self.markers):
            raw = self.query_one(f"#times_off_{i}", Input).value.strip()
            off = int(raw) if raw.isdigit() else _start
            out.append((time, wait, off, off))
        return out

    def focused_offset(self) -> int | None:
        """Offset of the marker input currently focused (or ``None``)."""
        f = self.screen.focused
        if isinstance(f, Input) and f.id and f.id.startswith("times_off_"):
            i = int(f.id.split("_")[-1])
            return self.markers_from_inputs()[i][2]
        return None

    def _bump_offset(self, delta: int) -> None:
        """Increment/decrement the focused marker's offset by ``delta``.

        Runs at key-repeat speed with no artificial throttling; writing
        ``input.value`` fires ``Input.Changed`` so the debounced highlight
        follows on the next pause.
        """
        f = self.screen.focused
        if not (isinstance(f, Input) and f.id and f.id.startswith("times_off_")):
            return
        item = self.app_ref.current_item
        vn = item.vn if item is not None else ""
        raw = f.value.strip()
        off = int(raw) if raw.isdigit() else 1
        new = max(1, min(off + delta, max(1, len(vn))))
        if new != off:
            f.value = str(new)

    def key_up(self) -> None:
        self._bump_offset(1)

    def key_down(self) -> None:
        self._bump_offset(-1)

    @on(Input.Changed)
    def _on_offset_change(self, event: Input.Changed) -> None:
        if event.input.id and event.input.id.startswith("times_off_"):
            self.app_ref._schedule_sync_highlight()

    def reload(self) -> bool:
        """Re-read markers for the current item; ``False`` if incompatible.

        Called on item switch while the panel is open: the tuned snapshot may
        change, so rebuild the inputs from it (same marker count) and refresh
        the highlight. Returns ``False`` when the new item has no markers or a
        different count, so the app can close the panel.
        """
        from tr_edit_core import tuned_times
        item = self.app_ref.current_item
        if item is None:
            return False
        base = item.file[:-len(".msg")]
        rids = [r for r in item.ids if tuned_times(self.app_ref.store, base, r)]
        if not rids or len(rids) != len(self.rids):
            return False
        new = list(tuned_times(self.app_ref.store, base, rids[0]))
        if len(new) != len(self.markers):
            return False
        self.markers = new
        for i, (time, wait, start, end) in enumerate(self.markers):
            self.query_one(f"#times_off_{i}", Input).value = str(start)
        self.app_ref._schedule_sync_highlight()
        return True

    @on(Button.Pressed)
    def _on_button(self, event: Button.Pressed) -> None:
        if event.button.id == "times_cancel":
            self.app_ref.close_slot()
        elif event.button.id == "times_do":
            self._save()

    def _save(self) -> None:
        app = self.app_ref
        item = app.current_item
        if item is None:
            app.close_slot()
            return
        base = item.file[:-len(".msg")]
        out = {}
        for i, (time, wait, start, end) in enumerate(self.markers):
            inp = self.query_one(f"#times_off_{i}", Input).value.strip()
            if not inp.isdigit():
                self.notify(f"Offset {i} is not a number", severity="warning")
                return
            off = int(inp)
            out[str(i)] = [off, off]
        for rid in self.rids:
            ov = app.store.overrides.setdefault(base, {}).setdefault(rid, {})
            ov["times_"] = out
        app.store.save_all()
        self.notify(f"Saved {len(out)} voice-sync marker(s) - rebuild the "
                    "patch for the game to pick them up")
        app.close_slot()
        if app.current_item is not None:
            app._refresh_preview()


class SlotMenu(Vertical):
    """Inline option menu hosted in #inline_panel (instead of a popup).

    Subclasses provide the options (via ``compose`` / RadioSet or similar) and
    call ``self.app_ref.close_slot()`` after picking. Everything here runs
    inside the normal app tree, so navigation throughout the UI stays usable
    while the menu is open.
    """

    def __init__(self, app):
        super().__init__()
        self.app_ref = app


class CopyMenu(SlotMenu):
    """Inline menu letting you copy just the file or just the ID."""

    def __init__(self, app, item):
        super().__init__(app)
        self.item = item

    def compose(self) -> ComposeResult:
        yield Static("[b]Copy item: pick one field[/b]", id="copy-title")
        yield RadioSet(
            RadioButton("file", id="copy_file"),
            RadioButton("ID", id="copy_id"),
        )
        with Horizontal(id="copy-actions"):
            yield Button("Copy", id="copy_do", variant="primary")
            yield Button("Cancel", id="copy_cancel")

    @on(Button.Pressed)
    def _on_button(self, event: Button.Pressed) -> None:
        if event.button.id == "copy_cancel":
            self.app_ref.close_slot()
        elif event.button.id == "copy_do":
            self._do_copy()

    def _do_copy(self) -> None:
        rs = self.query_one(RadioSet)
        choice = None
        for rb in rs.query(RadioButton):
            if rb.value:
                choice = rb.id
                break
        app = self.app_ref
        if choice == "copy_file":
            app._clip("file", self.item.file)
        elif choice == "copy_id":
            ids = ", ".join(self.item.ids) or "(no id)"
            app._clip("ID", ids)
        else:
            app.notify("Pick file or ID", severity="warning")
            return
        app.close_slot()


class PrefixSuggester(Suggester):
    """Shell-style completion for a filter input.

    Suggests the first candidate that starts with the typed value (case
    insensitive). The ghost text shows in the input and the built-in
    right-arrow binding accepts it. ``candidates`` is a callable returning the
    list (evaluated lazily so it reflects current data), or a plain list.
    """

    def __init__(self, candidates):
        super().__init__(case_sensitive=False, use_cache=False)
        self._candidates = candidates

    def _list(self):
        return self._candidates() if callable(self._candidates) \
            else self._candidates

    async def get_suggestion(self, value):
        if not value:
            return None
        v = value.strip().lower()
        for c in self._list():
            if c.lower().startswith(v) and c.lower() != v:
                return c
        return None


class TrEditApp(App):
    """Browse and edit translation items with inline markers."""

    TITLE = "Translation Editor"
    SUB_TITLE = "text + markers  |  Ctrl+S save, Ctrl+R reset"

    CSS = """
    .filters {
        height: 3;
        padding: 0 1;
        border: round $primary;
    }
    .filters Input {
        width: 1fr;
        border: none;
    }
    #search {
        width: 33%;
    }
    #file {
        width: 1fr;
    }
    #range {
        width: 12;
        min-width: 10;
    }
    #id {
        width: 1fr;
    }
    #speaker {
        width: 14;
        min-width: 10;
    }
    .main {
        height: 1fr;
    }
    .pane {
        width: 1fr;
        height: 1fr;
    }
    .pane-left {
        width: 33%;
    }
    #preview_sc {
        height: 1fr;
        border: round $primary;
        padding: 0 1;
        overflow-y: auto;
        scrollbar-gutter: stable;
        scrollbar-size: 1 1;
        scrollbar-color: $accent;
        scrollbar-background: $panel;
    }
    #preview {
        width: 1fr;
        height: auto;
    }
    #hint {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    #bottom_slot {
        height: 1fr;
    }
    #legend_sc {
        height: 1fr;
        border: round $secondary;
        padding: 0 1;
        overflow-y: auto;
        scrollbar-gutter: stable;
        scrollbar-size: 1 1;
        scrollbar-color: $accent;
        scrollbar-background: $panel;
        color: $text-muted;
    }
    #legend {
        width: 1fr;
        height: auto;
    }
    #inline_panel {
        height: 1fr;
        border: round $accent;
        padding: 0 1;
        overflow-y: auto;
    }
    #inline_panel.hidden {
        display: none;
    }
    #table {
        height: 1fr;
    }
    ToastRack {
        margin-bottom: 5;
        align: right bottom;
    }
    #editor_head {
        height: 1;
        color: $text;
        background: $panel;
        padding: 0 1;
    }
    #editor {
        height: 1fr;
        border: round $accent;
    }
    #editor_stats {
        height: auto;
        color: $text-muted;
        padding: 0 1;
    }
    #replace_panel {
        height: auto;
    }
    #times_panel {
        height: auto;
    }
    #times_panel #times-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #times_panel #times-scroll {
        height: auto;
        max-height: 8;
        overflow-y: auto;
        scrollbar-gutter: stable;
        scrollbar-size: 1 1;
    }
    #times_panel Label {
        color: $text-muted;
        margin-top: 1;
    }
    #times_panel .times-row {
        height: auto;
        align: left middle;
        margin-top: 0;
    }
    #times_panel .times-row Input {
        width: 6;
        min-width: 5;
        height: 1;
        min-height: 1;
        border: none;
        padding: 0 1;
    }
    #times_panel .times-meta {
        color: $text-muted;
        margin-left: 1;
    }
    #times_panel #times-actions {
        height: auto;
        align: right middle;
        margin-top: 1;
        width: auto;
    }
    #times_panel #times-actions Button {
        height: 1;
        min-height: 1;
        width: 11;
        min-width: 10;
        border: none;
        margin-left: 1;
        padding: 0 2;
    }
    #replace_panel #replace-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #replace_panel .replace-sub {
        color: $text-muted;
        margin-top: 1;
    }
    #replace_panel Label {
        margin-top: 1;
    }
    #replace-grid {
        height: auto;
        margin-top: 1;
    }
    #replace-grid .replace-row {
        height: auto;
        align: left middle;
        padding: 0 1;
    }
    #replace-grid .replace-fill {
        width: 1fr;
    }
    #replace-grid Checkbox {
        height: 1;
        min-height: 1;
        border: none;
        margin-right: 1;
        padding: 0 2;
    }
    #replace-grid Button {
        height: 1;
        min-height: 1;
        width: 11;
        border: none;
        margin-left: 1;
        padding: 0 2;
    }
    #replace_count {
        height: 1;
        color: $text-muted;
        margin-top: 1;
    }
    #replace_preview {
        height: auto;
        max-height: 8;
        border: round $primary 40%;
        padding: 0 1;
        margin-top: 1;
        overflow-y: auto;
    }
    #inline_panel SlotMenu {
        height: 1fr;
    }
    #copy-title {
        text-style: bold;
        margin-bottom: 1;
    }
    SlotMenu RadioSet {
        height: auto;
        margin: 1 0;
    }
    SlotMenu RadioButton {
        height: 3;
        min-height: 3;
        padding: 0 2;
        margin-bottom: 1;
    }
    SlotMenu RadioButton > .radio--label {
        padding: 0 1;
        text-style: bold;
    }
    #copy-actions {
        height: auto;
        align: right middle;
        margin-top: 1;
    }
    #copy-actions Button {
        height: 1;
        min-height: 1;
        min-width: 8;
        border: none;
        margin-left: 1;
        padding: 0 2;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+s", "save_edit", "Save", show=True),
        Binding("ctrl+r", "reset_edit", "Reset", show=True),
        Binding("ctrl+e", "focus_editor", "Edit", show=True),
        Binding("ctrl+f", "focus_search", "Search", show=True),
        Binding("ctrl+l", "focus_file", "File", show=True),
        Binding("ctrl+n", "next_file", "Next file", show=True),
        Binding("escape", "clear_filters", "Reset", show=True),
        Binding("pagedown", "scroll_panel_down", "Panel dn", show=False),
        Binding("pageup", "scroll_panel_up", "Panel up", show=False),
        Binding("ctrl+t", "copy_vn", "Copy VN", show=False),
        Binding("ctrl+j", "copy_ja", "Copy JA", show=False),
        Binding("ctrl+g", "copy_en", "Copy EN", show=False),
        Binding("ctrl+o", "copy_compound", "Copy cmpnd", show=False),
        Binding("ctrl+m", "copy_item", "Copy item", show=False),
        Binding("ctrl+h", "copy_debug", "Copy debug", show=False),
        Binding("f4", "toggle_en_markers", "EN markers", show=False),
        Binding("f3", "auto_wrap", "Wrap", show=False),
        Binding("f2", "open_replace", "Replace rule", show=False),
        Binding("f5", "apply_replace", "Apply rule", show=False),
        Binding("f9", "open_times", "Sync times", show=False),
        Binding("ctrl+up", "prev_item", "Prev item", show=False),
        Binding("ctrl+down", "next_item", "Next item", show=False),
        Binding("f8", "view_context", "Context", show=False),
        Binding("ctrl+q", "quit", "Quit", show=False),
    ]

    def __init__(self, game_dir=None, default_file=None):
        super().__init__()
        self.store = Store(game_dir=game_dir)
        if default_file:
            default_file = default_file.removesuffix(".msg")
            self.base = default_file
        else:
            self.base = ""   # empty = browse all tables
        self._search_timer = None
        self._search_armed_query = ""
        self._skip_search_debounce = False
        self._times_timer = None   # debounced live sync-highlight (F9 panel)
        self._skip_range_sync = False
        self._skip_filter_refresh = False
        self.range = None   # (start, end) inclusive, or None
        self.items = []            # filtered Item list in table order
        self.items_idx = []        # enumeration index per self.items entry
        self.current_key = None    # (file, en) currently in the editor
        self.current_item = None   # Item currently in the editor
        self.dirty = False
        self._loaded = None        # last programmatic editor text
        self._suppress_highlight = False  # set during refresh's own selection
        self._en_markers = False   # show EN with game highlight markers
        self.replace_rule = None   # session regex rule set via the F2 dialog

    # -- composition -------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            with Horizontal(classes="filters"):
                yield Input(placeholder="search EN / VN / ID (* ? wildcards)",
                            id="search")
                yield Input(placeholder="index", id="range")
                yield Input(placeholder="file base (e.g. text_scenario_030)",
                            value=self.base, id="file",
                            suggester=PrefixSuggester(self._file_bases))
                yield Input(placeholder="ID", id="id",
                            suggester=PrefixSuggester(self._all_ids))
                yield Input(placeholder="Speaker", id="speaker",
                            suggester=PrefixSuggester(self._speaker_names))
            with Horizontal(classes="main"):
                with Vertical(classes="pane pane-left"):
                    with ScrollableContainer(id="preview_sc"):
                        yield Static("(select an item)", id="preview")
                    yield Static("", id="hint")
                    with Vertical(id="bottom_slot"):
                        with ScrollableContainer(id="legend_sc"):
                            yield Static(LEGEND, id="legend")
                        with Vertical(id="inline_panel", classes="hidden"):
                            pass
                with Vertical(classes="pane"):
                    yield DataTable(id="table", zebra_stripes=True,
                                    cursor_type="row")
                    yield Static("", id="editor_head")
                    yield TextArea(id="editor")
                    yield Static("", id="editor_stats")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#table", DataTable)
        table.add_column("N", key="n", width=5)
        table.add_column("FILE", key="file", width=19)
        table.add_column("ID", key="id", width=22)
        table.add_column("SPK", key="spk", width=14)
        table.add_column("EN", key="en")
        # make the preview/legend scroll containers focusable so PageUp/
        # PageDown/arrows/mouse-wheel scroll them (they are by default)
        self.query_one("#preview_sc", ScrollableContainer).can_focus = True
        self.query_one("#legend_sc", ScrollableContainer).can_focus = True
        self.refresh_table()

    # -- table population --------------------------------------------------

    def refresh_table(self, keep_key=None) -> None:
        store, base = self.store, self.base
        q = self.query_one("#search", Input).value.strip()
        q_id = self.query_one("#id", Input).value.strip().lower()
        q_sp = self.query_one("#speaker", Input).value.strip().lower()
        bases = {base} if base else None
        lo, hi = self.range if self.range is not None else (None, None)
        found = []
        found_idx = []
        idx = 0
        for it in iter_scan(store, bases=bases):
            # The range filters on the item's position in this table's (or the
            # whole-database) enumeration, stable regardless of the search
            # query, so view_context can compute it once and expand outwards.
            if lo is not None and idx < lo:
                idx += 1
                continue
            if hi is not None and idx > hi:
                break
            if q and not matches(store, it, q):
                idx += 1
                continue
            if q_id and not any(q_id in rid.lower() for rid in it.ids):
                idx += 1
                continue
            if q_sp and q_sp not in (it.speaker or "").lower():
                idx += 1
                continue
            found.append(it)
            found_idx.append(idx)
            idx += 1
            if len(found) >= MAX_ROWS:
                break
        table = self.query_one("#table", DataTable)
        table.clear()
        self.items = found
        self.items_idx = found_idx
        self.rows_by_key = {it.file + "\u0000" + it.key: it for it in found}
        for i, it in enumerate(found):
            ids = ",".join(it.ids[:2])
            if len(it.ids) > 2:
                ids += "…"
            en_line = it.en.split("\n", 1)[0]
            if len(en_line) > 46:
                en_line = en_line[:45] + "…"
            nid = it.file[:-len(".msg")]
            if len(nid) > 18:
                nid = nid[:17] + "…"
            table.add_row(str(found_idx[i]), nid, ids or "-",
                          (it.speaker or "")[:14] or "-",
                          en_line, key=(it.file, it.key))
        # selection: keep the current row while editing (dirty), else pick
        # first / preserved key. RowHighlighted does not re-fire after a
        # full repopulate, so select + load explicitly. Guard against the
        # RowHighlighted that Textual still emits for the old row afterwards.
        self._suppress_highlight = True
        sel_key = keep_key
        if not sel_key and self.current_key is not None:
            sel_key = (self.current_key[0], self.current_key[1])
        if sel_key:
            skey = sel_key[0] + "\u0000" + sel_key[1]
        else:
            skey = None
        if skey and skey in self.rows_by_key:
            # Locate the row index by scanning self.items on the (file, en)
            # string key. get_row_index fails silently (RowDoesNotExist) when
            # duplicate (file, en) rows collapse the dict lookup, leaving the
            # cursor stranded at the previous row after clear()+repopulate.
            skey = sel_key[0] + "\u0000" + sel_key[1]
            target_idx = next((i for i, r in enumerate(self.items)
                               if r.file + "\u0000" + r.key == skey), None)
            if target_idx is None:
                try:
                    target_idx = table.get_row_index(sel_key)
                except Exception:  # noqa: BLE001 - row may have been filtered out
                    target_idx = None
            if target_idx is not None:
                table.move_cursor(row=target_idx)
            if not self.dirty:
                self.load_item(self.rows_by_key[skey])
        elif found:
            table.move_cursor(row=0)
            self.current_key = None
            self.load_item(found[0])
        else:
            self.current_key = None
            self.current_item = None
            self.query_one("#preview", Static).update("(no items)")
            self.query_one("#editor_head", Static).update("Speaker: -")
            self.query_one("#editor", TextArea).text = ""
            self._loaded = ""
            self.dirty = False
            self.update_editor_stats()
        self.set_hint()
        # clear the suppression on the next frame (synthetic RowHighlighted
        # for the old row is emitted in the same message batch)
        self.set_timer(0.1, lambda: setattr(self, "_suppress_highlight", False))

    def set_hint(self) -> None:
        n = len(self.items)
        scope = f"{self.base}.msg" if self.base else "all files"
        if self.range is not None and self.items_idx:
            lo, hi = self.items_idx[0], self.items_idx[-1]
            rng = f"idx {lo}-{hi}" if lo != hi else f"idx {lo}"
        else:
            rng = ""
        self.query_one("#hint", Static).update(
            f"{n} item(s) · {scope} {rng}".strip() + " · "
            "Ctrl+S save · Ctrl+R reset · Ctrl+F search · F4 EN · F3 wrap")

    # -- selection / editor ------------------------------------------------

    @on(DataTable.RowHighlighted)
    def on_row(self, event: DataTable.RowHighlighted) -> None:
        table = self.query_one("#table", DataTable)
        if event.row_key is None or event.row_key.value is None:
            return
        if self._suppress_highlight:
            self._suppress_highlight = False
            return
        key = event.row_key.value
        item = self.rows_by_key.get(key[0] + "\u0000" + key[1])
        if item is None:
            return
        if self.dirty:
            self.notify("Editor has unsaved changes - Ctrl+S to save, "
                        "Ctrl+R to discard", severity="warning", timeout=4)
            try:
                table.move_cursor(row=table.get_row_index(
                    (self.current_key[0], self.current_key[1])))
            except Exception:  # noqa: BLE001, S110 - cursor already outside table
                pass
            return
        # A RowHighlighted can re-fire for the already-loaded row (e.g. after
        # the editor text is set programmatically), which would reload the old
        # item over the current one. Skip when it is the same item.
        if (self.current_key is not None
                and key[0] == self.current_key[0]
                and key[1] == self.current_key[1]):
            return
        self.load_item(item)

    def load_item(self, item) -> None:
        item = self._full_item(item)
        self.current_key = (item.file, item.key)
        self.current_item = item
        self._render_preview(item)
        spk = item.speaker or "(none)"
        self.query_one("#editor_head", Static).update(
            f"[b]Speaker:[/b] {spk}   [b](read-only, not counted)[/b]")
        editor = self.query_one("#editor", TextArea)
        editor.text = build_compound(item, with_speaker=False)
        # remember the programmatic value so TextArea.Changed fired for this
        # load is not mistaken for a user edit (the event is async)
        self._loaded = editor.text
        self.dirty = False
        self.update_editor_stats()
        self._refresh_panel()

    def _full_item(self, item):
        """Materialize a light ScanItem into a full Item (once, cached)."""
        if isinstance(item, ScanItem):
            item = item.materialize(self.store)
            self.rows_by_key[item.file + "\u0000" + item.key] = item
        return item

    def _render_preview(self, item) -> None:
        ids = ", ".join(item.ids) or "(no id)"
        from tr_edit_core import en_compound, tuned_times
        base = item.file[:-len(".msg")]
        sync_offs = []
        for rid in item.ids:
            for _t, _w, s, e in tuned_times(self.store, base, rid):
                sync_offs.append(s)
                if e != s:
                    sync_offs.append(e)
            if sync_offs:
                break
        if self._en_markers:
            en_view = self._highlight_en(en_compound(self.store, item),
                                         item.file, item.ids)
        else:
            en_view = self._rich_esc(item.en)
        prev = (f"[b]{item.file}[/b]  {ids}\n"
                f"[b]EN{'+' if self._en_markers else ''}:[/b]\n{en_view}\n"
                f"[b]VN (plain):[/b]\n{self._highlight_vn(item.vn, sync_offs)}\n"
                f"[b]JA (raw):[/b]\n{self._rich_esc(self.store.ja_text(item.file, item.ids) or '(no JA)')}")
        prev = self._append_times_preview(prev, item)
        self.query_one("#preview", Static).update(prev)
        self._remeasure_panel("preview_sc")

    def _refresh_preview(self) -> None:
        """Re-render only the preview for the current item (no editor reset)."""
        if self.current_item is not None:
            self._render_preview(self.current_item)

    # -- live voice-sync highlight (F9 panel) ------------------------------

    def _offset_to_location(self, text: str, idx: int) -> tuple[int, int]:
        """Map a flat character index into ``text`` to a (row, col) location."""
        idx = min(idx, len(text))
        row = text.count("\n", 0, idx)
        last_nl = text.rfind("\n", 0, idx)
        return (row, idx - (last_nl + 1))

    def _set_sync_highlight(self, off: int | None = None) -> None:
        """Highlight the voice-sync pause char for ``off`` inside the editor.

        The F9 panel edits ``times_`` offsets while the focus stays on the
        panel; a TextArea selection still renders when the widget is not
        focused, so the pause point is shown live in the editor. The pause
        sits at ``off - 1`` (the first char of the next reveal segment is at
        ``off``), walking back over trailing spaces like the preview tint.
        """
        from textual.document._document import Selection

        from tr_edit_core import vn_index_to_compound
        editor = self.query_one("#editor", TextArea)
        empty = Selection((0, 0), (0, 0))
        if off is None or self.current_item is None:
            editor.selection = empty
            return
        vn = self.current_item.vn
        j = min(off - 1, len(vn) - 1)
        if j < 0:
            editor.selection = empty
            return
        while j >= 0 and vn[j].isspace():
            j -= 1
        if j < 0:
            editor.selection = empty
            return
        compound = editor.text
        idx = vn_index_to_compound(compound, vn, j)
        start = self._offset_to_location(compound, idx)
        line = compound.split("\n")[start[0]]
        end = (start[0], min(start[1] + 1, len(line)))
        editor.selection = Selection(start, end)

    def _clear_sync_highlight(self) -> None:
        """Reset the editor selection to empty (close the F9 panel)."""
        try:
            self._set_sync_highlight(None)
        except Exception:  # noqa: BLE001, S110 - editor may not exist yet
            pass

    def _schedule_sync_highlight(self) -> None:
        """Debounce the live highlight recompute (mirrors the search box).

        Each keystroke / arrow tap arms a short timer; the selection is
        written only after the user pauses, so spamming Up/Down does not
        rewrite the editor on every repeat.
        """
        if self._times_timer is not None:
            self._times_timer.stop()
        self._times_timer = self.set_timer(0.15, self._do_sync_highlight)

    def _do_sync_highlight(self) -> None:
        """Apply the highlight for the F9 marker currently focused (or clear)."""
        self._times_timer = None
        if self.current_item is None:
            return
        panel = self.query_one("#inline_panel", Vertical)
        if "hidden" in panel.classes:
            return
        ts = next((c for c in panel.children if isinstance(c, TimesPanel)), None)
        if ts is None:
            return
        self._set_sync_highlight(ts.focused_offset())

    def _append_times_preview(self, prev, item) -> None:
        """Append a ``times_`` voice-sync line to the preview (if any markers).

        The markers are read from tag_tuning.json (the tuned snapshot). Each is
        shown as ``@offset time=Ns wait`` so a translator can spot sync points
        and open the Times panel (F9) to fix an offset manually.
        """
        from tr_edit_core import tuned_times
        for rid in item.ids:
            markers = tuned_times(self.store, item.file[:-len(".msg")], rid)
            if not markers:
                continue
            parts = []
            for time, wait, start, end in markers:
                label = f"@{start}" if start == end else f"@{start}-{end}"
                parts.append(f"[b]{label}[/b] {time:.2f}s"
                             + (" wait" if wait else ""))
            if parts:
                prev += "\n[b]Sync:[/b]  " + "   ".join(parts)
            break
        return prev

    def _refresh_panel(self) -> None:
        """Re-evaluate any open inline panel (e.g. ReplacePanel) for the new
        current item, so live counts/previews follow item switches."""
        slot = self.query_one("#inline_panel", Vertical)
        if "hidden" in slot.classes:
            return
        for child in slot.children:
            if isinstance(child, ReplacePanel):
                try:
                    child.count()
                except Exception:  # noqa: BLE001, S110 - keep the UI alive
                    pass
            elif isinstance(child, TimesPanel):
                # The tuned snapshot may differ for the new item; close the
                # panel when it no longer applies (no markers / different
                # count) rather than showing stale offsets.
                try:
                    if not child.reload():
                        self.close_slot()
                except Exception:  # noqa: BLE001 - keep the UI alive
                    self.close_slot()

    def _rich_esc(self, s: str) -> str:
        """Escape rich-markup metacharacters in ``s`` for a Static.update.

        A literal ``[`` must be written as ``\\[`` (otherwise sequences like
        ``[b]`` inside dialogue are consumed as markup tags); ``]`` is safe
        on its own in Rich 15.
        """
        return s.replace("[", "\\[")

    def _remeasure_panel(self, container_id: str) -> None:
        """Force the scroll container to re-measure its content.

        Textual caches content height by width; an update issued during the
        mount layout pass can capture a stale (too small) height that never
        refreshes, so the panel cannot be scrolled. Invalidating the cached
        dimensions on the next frame makes the container pick up the real
        content height.
        """
        container = self.query_one(f"#{container_id}", ScrollableContainer)
        child = self.query_one("#preview", Static) if container_id == "preview_sc" \
            else self.query_one("#legend", Static)

        def _invalidate() -> None:
            child.clear_cached_dimensions()
            container.clear_cached_dimensions()
            container.refresh(repaint=True, layout=True)

        self.set_timer(0.1, _invalidate)

    def _highlight_vn(self, vn: str, sync_offs=()) -> str:
        """Render ``vn`` with search matches in reverse video and voice-sync
        markers (``times_`` offsets) tinted a faint accent so the pause point
        is visible at a glance.

        A ``times_`` marker offsets the first character of the *next* reveal
        segment; the engine pauses right after the character before it, so the
        actual pause sits at ``offset - 1``. Each marker tints that single
        character so a translator can see the pause point at a glance.
        """
        q = self.query_one("#search", Input).value.strip()
        from tr_edit_core import _WILDCARD_RE, _norm_key, _wildcard_regex
        norm = _norm_key(vn)
        if q:
            if _WILDCARD_RE.search(q):
                rx = _wildcard_regex(_norm_key(q))
                spans = [(m.start(), m.end()) for m in rx.finditer(norm)]
            else:
                qn = _norm_key(q)
                spans = []
                i = 0
                while True:
                    i = norm.find(qn, i)
                    if i < 0:
                        break
                    spans.append((i, i + len(qn)))
                    i += len(qn)
        else:
            spans = []
        # map each times_ offset to the pause character. The engine pauses
        # right after the character at ``offset - 1`` (the first char of the
        # *next* reveal segment is at ``offset``), so the tint sits there,
        # walking back over any trailing space for a crisper marker.
        marks = {}
        for off in sync_offs:
            if off <= 0:
                continue
            j = min(off - 1, len(vn) - 1)
            while j >= 0 and vn[j].isspace():
                j -= 1
            if j >= 0:
                marks[j] = True
        if not spans and not marks:
            return self._rich_esc(vn)
        # render char by char: reverse video for search hits, blue background
        # for voice-sync pause chars (search wins on overlap).
        span_set = set()
        for s, e in spans:
            span_set.update(range(s, e))
        out = []
        for i, ch in enumerate(vn):
            if i in span_set:
                out.append(f"[reverse]{self._rich_esc(ch)}[/]")
            elif i in marks:
                out.append(f"[on #7aa6d9]{self._rich_esc(ch)}[/]")
            else:
                out.append(self._rich_esc(ch))
        return "".join(out)

    def _highlight_en(self, en_view: str, file: str, ids) -> str:
        """Tint the EN+ preview's voice-sync pause chars.

        ``en_view`` is the EN compound with highlight markers
        (``en_compound``); the ``times_`` offsets read from the EN tag index the
        plain EN string and land on the char after the pause punctuation, so
        each is first moved back to the punctuation (like ``_highlight_vn``),
        then mapped through ``en_index_at`` to the compound position and given
        the same blue tint as the VN line.
        """
        from tr_edit_core import en_index_at
        offs = self.store.en_times_offsets(file, ids)
        if not offs:
            return en_view
        plain_en = self.current_item.en
        marks = set()
        for off in offs:
            j = off
            while j > 0 and plain_en[j - 1].isspace():
                j -= 1
            if j > 0:
                j -= 1
            ci = en_index_at(en_view, plain_en, j)
            if 0 <= ci < len(en_view):
                marks.add(ci)
        if not marks:
            return en_view
        out = []
        for i, ch in enumerate(en_view):
            if i in marks:
                out.append(f"[on #7aa6d9]{self._rich_esc(ch)}[/]")
            else:
                out.append(self._rich_esc(ch))
        return "".join(out)

    @on(TextArea.Changed)
    def on_edit(self, event) -> None:
        if self._loaded is not None and event.text_area.text == self._loaded:
            self.dirty = False
            self.update_editor_stats()
            return
        self.dirty = True
        self.update_editor_stats()

    @on(TextArea.SelectionChanged)
    def on_cursor(self, _event) -> None:
        self.update_editor_stats()

    def update_editor_stats(self) -> None:
        editor = self.query_one("#editor", TextArea)
        text = editor.text
        words = len(text.split())
        chars = len(text)
        row, col = editor.cursor_location
        lines = text.split("\n")
        tallest = max((len(line) for line in lines), default=0)
        enc = self.current_item.en if self.current_item is not None else ""
        wrap = max((len(line) for line in enc.split("\n")), default=0)
        # cursor offset in the editor text (newlines counted), then mapped to
        # the plain-VN index so markers ({p}, {c:..}) don't shift the count.
        # Show vn_idx + 1: with the cursor on a character (e.g. a ``.``/`,`/
        # ``?``), the times_ marker offset the engine expects is one PAST it
        # (the pause lands at offset-1), so +1 is exactly the value to type.
        cur_off = sum(len(line) for line in lines[:row]) + row + col
        from tr_edit_core import vn_index_at
        vn_idx = vn_index_at(text, cur_off)
        self.query_one("#editor_stats", Static).update(
            f"words {words} · chars {chars} · cursor {row + 1}:{col + 1} · "
            f"longest line {tallest}ch · EN wrap {wrap}ch · "
            f"offset to type {vn_idx + 1}")

    # -- actions -----------------------------------------------------------

    def action_save_edit(self) -> None:
        if not self.current_key:
            self.notify("No item selected", severity="warning")
            return
        editor = self.query_one("#editor", TextArea)
        compound = editor.text
        item = self.rows_by_key.get(self.current_key[0] + "\u0000"
                                    + self.current_key[1])
        if item is None:
            return
        item = self._full_item(item)
        warnings = apply_edit(self.store, item, compound)
        self.store.save_all()
        self.dirty = False
        self.load_item(item)
        self.set_hint()
        if warnings:
            self.notify("Saved with warnings:\n" + "\n".join(warnings),
                        severity="warning", timeout=6)
        else:
            self.notify("Saved to translations/decisions/overrides")

    def action_reset_edit(self) -> None:
        if not self.current_key:
            return
        item = self.rows_by_key.get(self.current_key[0] + "\u0000"
                                    + self.current_key[1])
        if item is None:
            return
        item = self._full_item(item)
        editor = self.query_one("#editor", TextArea)
        editor.text = build_compound(item, with_speaker=False)
        self._loaded = editor.text
        self.dirty = False
        self.update_editor_stats()
        self.notify("Reloaded saved compound string")

    # -- copy to clipboard -------------------------------------------------

    def _clip(self, label: str, text: str) -> None:
        if not text:
            self.notify(f"Nothing to copy ({label})", severity="warning")
            return
        self.copy_to_clipboard(text)
        first = next((ln.strip() for ln in text.split("\n") if ln.strip()),
                     "")
        if len(first) > 42:
            first = first[:41] + "…"
        self.notify(f"[b]{label}[/b] copied" + (f": {first}" if first else ""))

    def action_copy_vn(self) -> None:
        if self.current_item is None:
            return
        editor = self.query_one("#editor", TextArea)
        _speaker, vn, _hl, _pp = parse_compound(editor.text)
        self._clip("VN (plain)", vn)

    def action_copy_en(self) -> None:
        if self.current_item is None:
            return
        self._clip("EN", self.current_item.en)

    def action_copy_ja(self) -> None:
        if self.current_item is None:
            return
        ja = self.store.ja_text(self.current_item.file, self.current_item.ids)
        self._clip("JA (raw)", ja or "")

    def action_toggle_en_markers(self) -> None:
        """Toggle the EN preview between plain text and game-highlight markers."""
        self._en_markers = not self._en_markers
        if self.current_item is not None:
            self.load_item(self.current_item)
        self.notify("EN markers " + ("on" if self._en_markers else "off"),
                    timeout=2)

    def action_auto_wrap(self) -> None:
        """Reflow the current editor text to the EN wrap width."""
        if self.current_item is None:
            self.notify("No item selected", severity="warning")
            return
        from tr_edit_core import auto_wrap
        editor = self.query_one("#editor", TextArea)
        width = max((len(line) for line in self.current_item.en.split("\n")),
                    default=0)
        if width < 1:
            return
        editor.text = auto_wrap(editor.text, width)
        self._loaded = editor.text
        self.dirty = False
        self.update_editor_stats()
        self.notify(f"Auto-wrapped to {width}ch", timeout=2)

    def action_copy_compound(self) -> None:
        if self.current_item is None:
            return
        self._clip("Compound", self.query_one("#editor", TextArea).text)

    def action_copy_item(self) -> None:
        if self.current_item is None:
            return
        self.open_slot(CopyMenu(self, self.current_item))

    def action_copy_debug(self) -> None:
        if self.current_item is None:
            return
        import json as _json
        it = self.current_item
        store = self.store
        base = it.file[:-len(".msg")]
        editor = self.query_one("#editor", TextArea)
        spk, vn, highlights, player_pos = parse_compound(editor.text)
        speaker_records = {}
        for rid in it.ids:
            rec = store.speakers.get(rid)
            if rec:
                speaker_records[rid] = dict(rec)
        decisions = {rid: store.decisions.get(base, {}).get(rid)
                     for rid in it.ids}
        decisions = {k: v for k, v in decisions.items() if v}
        overrides = {rid: store.overrides.get(base, {}).get(rid)
                     for rid in it.ids}
        overrides = {k: v for k, v in overrides.items() if v}
        parts = [
            f"FILE      : {it.file}",
            f"BASE      : {base}",
            f"IDS       : {', '.join(it.ids) or '(no id)'}",
            f"SPEAKER   : {spk or it.speaker or '(none)'}",
            "SPEAKERS  : "
            + _json.dumps(speaker_records, ensure_ascii=False),
            "EN        : " + _json.dumps(it.en, ensure_ascii=False),
            "VN (plain): " + _json.dumps(vn, ensure_ascii=False),
            "COMPOUND  : " + _json.dumps(editor.text, ensure_ascii=False),
            "HIGHLIGHTS: "
            + _json.dumps(highlights, ensure_ascii=False),
            "PLAYER_POS: " + _json.dumps(player_pos),
            "DECISIONS : "
            + _json.dumps(decisions, ensure_ascii=False),
            "OVERRIDES : "
            + _json.dumps(overrides, ensure_ascii=False),
        ]
        self._clip("Debug", "\n".join(parts))

    def action_focus_editor(self) -> None:
        self.query_one("#editor", TextArea).focus()

    def _scroll_panel(self, delta: int) -> None:
        """Scroll the focused preview/legend panel by ``delta`` lines."""
        focused = self.screen.focused
        if focused is None or focused.id not in ("preview_sc", "legend_sc"):
            return
        focused.scroll_relative(y=delta)

    def action_scroll_panel_down(self) -> None:
        self._scroll_panel(1)

    def action_scroll_panel_up(self) -> None:
        self._scroll_panel(-1)

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_focus_file(self) -> None:
        self.query_one("#file", Input).focus()

    def action_focus_table(self) -> None:
        self.query_one("#table", DataTable).focus()

    def action_clear_filters(self) -> None:
        # ESC: clear every filter and return to the list. All inputs reset in
        # one refresh (the per-input handlers are suppressed below) so the
        # whole filtering state is wiped with a single pass.
        self._skip_filter_refresh = True
        self._skip_search_debounce = True
        self._skip_range_sync = True
        for ident in ("#search", "#id", "#speaker", "#file", "#range"):
            self.query_one(ident, Input).value = ""
        self.base = ""
        self.range = None
        if not self.dirty:
            self.current_key = None
        # release the flags on the next frame so real user edits refresh again
        self.set_timer(0.1, lambda: setattr(self, "_skip_filter_refresh", False))
        self.set_timer(0.1, lambda: setattr(self, "_skip_search_debounce", False))
        self.set_timer(0.1, lambda: setattr(self, "_skip_range_sync", False))
        self.refresh_table()
        self.query_one("#table", DataTable).focus()

    def action_next_file(self) -> None:
        files = sorted(self.store.tables)
        cur = self.base + ".msg"
        idx = files.index(cur) if cur in files else 0
        nxt = files[(idx + 1) % len(files)]
        self.base = nxt[:-len(".msg")]
        self.query_one("#file", Input).value = self.base
        self.current_key = None
        self.dirty = False
        self.refresh_table()

    # -- item navigation & replace -----------------------------------------

    def _step_item(self, delta: int) -> None:
        """Move the table cursor by ``delta`` rows and load the item."""
        table = self.query_one("#table", DataTable)
        if self.dirty:
            self.notify("Editor has unsaved changes - Ctrl+S to save, "
                        "Ctrl+R to discard", severity="warning", timeout=4)
            return
        if not table.row_count:
            return
        idx = (table.cursor_row + delta) % table.row_count
        try:
            table.move_cursor(row=idx)
        except Exception:  # noqa: BLE001 - table row vanished mid-scroll
            return
        key = table.get_row_at(idx)
        item = self.rows_by_key.get(key[0] + "\u0000" + key[1])
        if item is not None and self._suppress_highlight is False:
            self.load_item(item)

    def action_prev_item(self) -> None:
        self._step_item(-1)

    def action_next_item(self) -> None:
        self._step_item(1)

    def action_view_context(self) -> None:
        """Show the selected item's table context in the item list.

        Fills the file filter with the current item's table, clears the search
        so every row of that table is listed, and pins the index-range filter
        to a window around the item so its row is visible on screen. The item
        itself stays selected (the range keeps its key in the filtered set);
        the notification reports the exact index instead of jumping the cursor.
        """
        if self.current_item is None or self.dirty:
            if self.dirty:
                self.notify("Editor has unsaved changes - Ctrl+S to save, "
                            "Ctrl+R to discard", severity="warning", timeout=4)
            return
        it = self.current_item
        key = (it.file, it.key)
        # Cancel a pending debounced search so its delayed refresh_table cannot
        # run after us and reset the cursor back to the first row.
        if self._search_timer is not None:
            self._search_timer.stop()
            self._search_timer = None
            self._search_armed_query = ""
        # Suppress the async Input.Changed that clearing the box below posts;
        # without it on_search re-arms a timer that fires a redundant refresh
        # (see _debounced_search) and can nudge the cursor.
        self._skip_search_debounce = True
        self.set_timer(0.1, lambda: setattr(self, "_skip_search_debounce", False))
        self.base = it.file[:-len(".msg")]
        self.query_one("#file", Input).value = self.base
        search = self.query_one("#search", Input)
        if search.value:
            search.value = ""
        # Show the item's own file with a window of rows around it. The range
        # filter pins the table to a small contiguous slice, so the item's row
        # is always on screen without needing to scroll the full file.
        idx = self._enum_index_of(key)
        if idx < 0:
            self.notify("Could not find the item's index", severity="warning",
                        timeout=3)
            return
        lo = max(0, idx - CONTEXT_MARGIN)
        hi = idx + CONTEXT_MARGIN
        self.range = (lo, hi)
        # Setting the box posts a Changed to on_range; guard it so it does not
        # clear the selection and refresh again (which would drop the cursor
        # back to row 0).
        self._skip_range_sync = True
        self.query_one("#range", Input).value = f"{lo}-{hi}"
        self.set_timer(0.1, lambda: setattr(self, "_skip_range_sync", False))
        self.refresh_table()
        if self.dirty:
            return
        self.notify(f"Context: {self.base}.msg (item idx {idx})", timeout=6)

    def _enum_index_of(self, key) -> int:
        """Return the enumeration position of ``key=(file,id-key)`` inside its
        table (matching the index column), or -1 if never encountered before
        MAX_ROWS scanning is impractical for a huge file header check.
        """
        base = key[0]
        base = base.removesuffix(".msg")
        bases = {base} if base else None
        for idx, it in enumerate(iter_scan(self.store, bases=bases)):
            if it.file == key[0] and it.key == key[1]:
                return idx
        return -1

    # -- inline slot (replaces the legend panel, bottom-left) --------------

    def open_slot(self, widget) -> None:
        """Show a widget in #inline_panel, hiding the legend while it is open.

        The widget lives in the normal app tree (not a modal screen), so item
        navigation and all other bindings keep working while it is shown.
        """
        slot = self.query_one("#inline_panel", Vertical)
        slot.remove_children()
        slot.mount(widget)
        slot.remove_class("hidden")
        self.query_one("#legend_sc").display = False

    def close_slot(self) -> None:
        """Hide the inline slot and bring the legend back."""
        self._clear_sync_highlight()
        slot = self.query_one("#inline_panel", Vertical)
        slot.remove_children()
        slot.add_class("hidden")
        self.query_one("#legend_sc").display = True
        self.action_focus_table()

    def action_open_replace(self) -> None:
        self.open_slot(ReplacePanel(self))

    def action_open_times(self) -> None:
        """Open the voice-sync (times_) editor for the current item."""
        item = self.current_item
        if item is None:
            self.notify("No item open", severity="warning")
            return
        from tr_edit_core import tuned_times
        base = item.file[:-len(".msg")]
        rids = [r for r in item.ids if tuned_times(self.store, base, r)]
        if not rids:
            self.notify("This item has no voice-sync markers", severity="warning")
            return
        markers = tuned_times(self.store, base, rids[0])
        self.open_slot(TimesPanel(self, markers, rids))

    def action_apply_replace(self) -> None:
        """Apply the session replace rule (F2) to the current editor text."""
        rule = self.replace_rule
        if rule is None:
            self.notify("No replace rule set - press F2 to create one",
                        severity="warning")
            return
        if self.current_item is None:
            self.notify("No item open in the editor", severity="warning")
            return
        from tr_edit_core import replace_in_compound
        editor = self.query_one("#editor", TextArea)
        try:
            new_compound, n_subs, warns = replace_in_compound(
                editor.text, rule["rx"], rule["repl"])
        except re.error:
            self.notify("Invalid replacement text - fix the F2 rule",
                        severity="warning")
            return
        if n_subs == 0:
            self.notify("Rule matched nothing in the current item",
                        severity="warning")
            return
        # TextArea.Changed fires asynchronously after .text is set; because the
        # new text differs from _loaded the event marks the edit as dirty, so
        # Ctrl+S persists it and the dirty guard protects navigation.
        editor.text = new_compound
        self.update_editor_stats()
        msg = f"Replaced {n_subs} occurrence(s)"
        if warns:
            msg += "\n" + "\n".join(warns[:4])
            self.notify(msg + " - press Ctrl+S to save",
                        severity="warning", timeout=6)
        else:
            self.notify(msg + " - press Ctrl+S to save", timeout=3)

    # -- filter inputs -----------------------------------------------------

    @on(Input.Changed, "#search")
    def on_search(self, event: Input.Changed) -> None:
        # debounced search: refresh only after the user stops typing. A longer
        # delay avoids firing while the user is still hunting for characters
        # (slow typing with pauses longer than the threshold).
        if self._search_timer is not None:
            self._search_timer.stop()
        # This Changed comes right after view_context cleared the box; its only
        # purpose would be to refresh (which view_context already did), so skip
        # arming a timer that would re-fire a redundant refresh later.
        if self._skip_search_debounce:
            self._search_timer = None
            return
        self._search_armed_query = event.input.value
        self._search_timer = self.set_timer(0.6, self._debounced_search)

    def _debounced_search(self) -> None:
        self._search_timer = None
        if self._skip_search_debounce:
            return
        if self.query_one("#search", Input).value != self._search_armed_query:
            return
        # Only drop the selection reset policy when there is a real search
        # query. A cleared box (empty query, e.g. after view_context) must keep
        # the current item so refresh_table re-selects it instead of snapping
        # the cursor back to the first row.
        if self.query_one("#search", Input).value and not self.dirty:
            self.current_key = None
        self.refresh_table()

    # -- filter autocomplete ----------------------------------------------

    def _file_bases(self):
        """Sorted table basenames for the file filter suggestion."""
        return sorted({f[:-len(".msg")] for f in self.store.tables})

    def _all_ids(self):
        """Sorted row ids for the ID filter suggestion (cached per store).

        Under the ID-keyed table every stored key carries its row id (possibly
        suffixed with ``::subid``); the suggestion list keeps the id part.
        """
        cache = getattr(self.store, "_id_suggest_cache", None)
        if cache is None:
            cache = self.store._id_suggest_cache = set()
        if not cache and self.store.tables:
            for file in self.store.tables:
                if not file.startswith("text_scenario"):
                    continue
                for key in self.store.tables[file]:
                    cache.add(key.split("::", 1)[0])
        return sorted(cache)

    def _speaker_names(self):
        """Sorted speaker display names for the Speaker filter suggestion."""
        names = set()
        for rec in (self.store.speakers or {}).values():
            for k in ("name_en", "name_ja", "chara"):
                if rec.get(k):
                    names.add(rec[k])
        return sorted(names)

    @on(Input.Changed, "#file")
    def on_file(self, event: Input.Changed) -> None:
        self.base = event.value.strip()
        if self._skip_filter_refresh:
            return
        if not self.dirty:
            self.current_key = None
        self.refresh_table()

    @on(Input.Submitted, "#file")
    def on_file_submit(self, _event) -> None:
        self.query_one("#table", DataTable).focus()

    @on(Input.Changed, "#id")
    def on_id(self, event: Input.Changed) -> None:
        if self._skip_filter_refresh:
            return
        if not self.dirty:
            self.current_key = None
        self.refresh_table()

    @on(Input.Changed, "#speaker")
    def on_speaker(self, event: Input.Changed) -> None:
        if self._skip_filter_refresh:
            return
        if not self.dirty:
            self.current_key = None
        self.refresh_table()

    @on(Input.Changed, "#range")
    def on_range(self, event: Input.Changed) -> None:
        text = event.value.strip()
        new_range = self._parse_range(text)
        if self._skip_range_sync:
            # view_context programmatically set the box and already refreshed;
            # keep the range it chose without clearing the selection.
            self.range = new_range
            return
        self.range = new_range
        if not self.dirty:
            self.current_key = None
        self.refresh_table()

    @staticmethod
    def _parse_range(text: str):
        """Parse an inclusive idx range like '100-120' (or '100', '100-').

        Returns (lo, hi) with None for open ends, or None if the text is not a
        valid range.
        """
        if not text:
            return None
        m = re.fullmatch(r"\s*(\d+)(?:\s*-\s*(\d*))?\s*", text)
        if not m:
            return None
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else None
        # A bare number is a single row (range hi==lo); '100-' stays open-ended.
        if hi is None and not text.rstrip().endswith("-"):
            hi = lo
        if hi is not None and hi < lo:
            lo, hi = hi, lo
        return (lo, hi)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", default=None, help="game install dir")
    ap.add_argument("--file", default=None,
                    help="initial table basename, e.g. text_scenario_030")
    args = ap.parse_args()
    app = TrEditApp(game_dir=args.game, default_file=args.file)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
