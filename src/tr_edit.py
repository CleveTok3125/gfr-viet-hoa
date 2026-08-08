#!/usr/bin/env python3
"""TUI for editing the Vietnamese translations + highlight markers.

A full-screen editor built on `textual`. The editable text is a *compound
string*: the VN translation with marker tokens inline (see tr_edit_core for
the marker convention). Saving writes the parsed result back to
translations.json, decisions.json and tag_overrides.json.

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
    Ctrl+T/J/G/O/M/H  copy VN / JA / EN / compound / item info / debug
    F2                configure a regex search & replace rule (session)
    F5                apply the F2 rule to the current item's text
    Ctrl+Up / Ctrl+Down  previous / next item
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

from textual.app import App, ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.containers import (  # noqa: E402
    Horizontal, ScrollableContainer, Vertical)
from textual.widgets import (  # noqa: E402
    Button, Checkbox, DataTable, Footer, Header, Input, Label, RadioButton,
    RadioSet, Static, TextArea)
from textual import on  # noqa: E402

from common import bootstrap  # noqa: E402
bootstrap()

from tr_edit_core import (  # noqa: E402
    Store, iter_items, matches, build_compound, parse_compound, apply_edit)

MAX_ROWS = 3000

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
    "Ctrl+M   item info (file / id / speaker / EN / VN)\n"
    "Ctrl+H   full debug dump (ids, speaker, markers, decisions/overrides)\n"
    "\n"
    "[b]Preview[/b]\n"
    "F4        toggle EN preview: plain or with game highlight markers\n"
    "          ({c:}/{w:}/{b:} + {p} player-name insertion point)\n"
    "PgUp/PgDn scroll the focused preview / legend panel\n"
    "Ctrl+F    search (EN / VN / ID; * ? wildcards; \\n = space)\n"
    "Esc       clear search text, then back to the list\n"
    "F2        configure a regex search & replace rule (session)\n"
    "F5        apply the F2 rule to the current item's text\n"
    "Ctrl+Up/Down  previous / next item\n"
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
        yield Static("Saved for this session. Press F5 while editing any "
                     "item to apply it to the current text (Ctrl+S saves "
                     "the result).", classes="replace-sub")
        yield Label("Pattern (regex)")
        yield Input(placeholder=r"e.g. tàu bay|thuyền trưởng",
                    id="replace_pattern")
        yield Label("Replacement")
        yield Input(placeholder=r"e.g. phi thuyền", id="replace_repl")
        with Horizontal(id="replace-opts"):
            yield Checkbox("Match case", id="replace_case")
            yield Checkbox("Whole word", id="replace_word")
        yield Static("-", id="replace_count")
        yield Static("", id="replace_preview")
        with Horizontal(id="replace-actions"):
            yield Button("Save rule", id="replace_do", variant="primary")
            yield Button("Close", id="replace_close")

    def on_mount(self) -> None:
        app = self.app_ref
        rx = getattr(app, "replace_rule", None)
        if rx is not None:
            self.query_one("#replace_pattern", Input).value = rx["pattern"]
            self.query_one("#replace_repl", Input).value = rx["repl"]
            self.query_one("#replace_case", Checkbox).value = rx["case"]
            self.query_one("#replace_word", Checkbox).value = rx["word"]
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
            result, _subs, _warns = replace_in_compound(compound, rx, repl)
            prev.update("[b]Preview:[/b]\n" + result)
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
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    #replace_panel {
        height: 1fr;
    }
    #replace_panel #replace-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #replace_panel .replace-sub {
        color: $text-muted;
        margin-bottom: 1;
    }
    #replace_panel Label {
        margin-top: 1;
    }
    #replace-opts {
        height: auto;
        margin-top: 1;
    }
    #replace-opts Checkbox {
        height: auto;
        margin-right: 2;
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
    #replace-actions {
        height: 3;
        align: right middle;
    }
    #replace-actions Button {
        height: 3;
        min-height: 3;
        border: round $primary;
        margin-left: 1;
        padding: 0 1;
    }
    #inline_panel SlotMenu {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "save_edit", "Save", show=True),
        Binding("ctrl+r", "reset_edit", "Reset", show=True),
        Binding("ctrl+e", "focus_editor", "Edit", show=True),
        Binding("ctrl+f", "focus_search", "Search", show=True),
        Binding("ctrl+l", "focus_file", "File", show=True),
        Binding("ctrl+n", "next_file", "Next file", show=True),
        Binding("escape", "focus_table", "List", show=True),
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
        Binding("ctrl+up", "prev_item", "Prev item", show=False),
        Binding("ctrl+down", "next_item", "Next item", show=False),
        Binding("ctrl+q", "quit", "Quit", show=False),
    ]

    def __init__(self, game_dir=None, default_file=None):
        super().__init__()
        self.store = Store(game_dir=game_dir)
        if default_file:
            if default_file.endswith(".msg"):
                default_file = default_file[:-len(".msg")]
            self.base = default_file
        else:
            self.base = ""   # empty = browse all tables
        self._search_timer = None
        self.items = []            # filtered Item list in table order
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
                yield Input(placeholder="file base (e.g. text_scenario_030)",
                            value=self.base, id="file")
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
        bases = {base} if base else None
        held = {}
        found = []
        for it in iter_items(store, bases=bases, holds=held):
            if q and not matches(store, it, q):
                continue
            found.append(it)
            if len(found) >= MAX_ROWS:
                break
        table = self.query_one("#table", DataTable)
        table.clear()
        self.items = found
        self.rows_by_key = {it.file + "\u0000" + it.en: it for it in found}
        for n, it in enumerate(found):
            ids = ",".join(it.ids[:2])
            if len(it.ids) > 2:
                ids += "…"
            en_line = it.en.split("\n", 1)[0]
            if len(en_line) > 46:
                en_line = en_line[:45] + "…"
            nid = it.file[:-len(".msg")]
            if len(nid) > 18:
                nid = nid[:17] + "…"
            table.add_row(str(n), nid, ids or "-",
                          (it.speaker or "")[:14] or "-",
                          en_line, key=(it.file, it.en))
        # selection: keep the current row while editing (dirty), else pick
        # first / preserved key. RowHighlighted does not re-fire after a
        # full repopulate, so select + load explicitly. Guard against the
        # RowHighlighted that Textual still emits for the old row afterwards.
        self._suppress_highlight = True
        sel_key = keep_key
        if not sel_key and self.dirty and self.current_key is not None:
            sel_key = (self.current_key[0], self.current_key[1])
        if sel_key and sel_key in self.rows_by_key:
            try:
                table.move_cursor(row=table.get_row_index(sel_key))
            except Exception:
                pass
            if not self.dirty:
                self.load_item(self.rows_by_key[sel_key[0] + "\u0000"
                                                + sel_key[1]])
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
        self.query_one("#hint", Static).update(
            f"{n} item(s) · {scope} · "
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
            except Exception:
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
        self.current_key = (item.file, item.en)
        self.current_item = item
        ids = ", ".join(item.ids) or "(no id)"
        if self._en_markers:
            from tr_edit_core import en_compound
            en_view = self._rich_esc(en_compound(self.store, item))
        else:
            en_view = self._rich_esc(item.en)
        prev = (f"[b]{item.file}[/b]  {ids}\n"
                f"[b]EN{'+' if self._en_markers else ''}:[/b]\n{en_view}\n"
                f"[b]VN (plain):[/b]\n{self._highlight_vn(item.vn)}\n"
                f"[b]JA (raw):[/b]\n{self._rich_esc(self.store.ja_text(item.file, item.ids) or '(no JA)')}")
        self.query_one("#preview", Static).update(prev)
        self._remeasure_panel("preview_sc")
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

    def _highlight_vn(self, vn: str) -> str:
        """Render ``vn`` with search query matches wrapped in reverse video."""
        q = self.query_one("#search", Input).value.strip()
        if not q:
            return self._rich_esc(vn)
        from tr_edit_core import _WILDCARD_RE, _wildcard_regex, _norm_ws
        norm = _norm_ws(vn)
        if _WILDCARD_RE.search(q):
            rx = _wildcard_regex(_norm_ws(q))
            spans = [(m.start(), m.end()) for m in rx.finditer(norm)]
        else:
            qn = _norm_ws(q).lower()
            nl = norm.lower()
            spans = []
            i = 0
            while True:
                i = nl.find(qn, i)
                if i < 0:
                    break
                spans.append((i, i + len(qn)))
                i += len(qn)
        if not spans:
            return self._rich_esc(vn)
        out = []
        cur = 0
        for s, e in spans:
            out.append(self._rich_esc(vn[cur:s]))
            out.append(f"[reverse]{self._rich_esc(vn[s:e])}[/reverse]")
            cur = e
        out.append(self._rich_esc(vn[cur:]))
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
        tallest = max((len(line) for line in text.split("\n")), default=0)
        enc = self.current_item.en if self.current_item is not None else ""
        wrap = max((len(line) for line in enc.split("\n")), default=0)
        self.query_one("#editor_stats", Static).update(
            f"words {words} · chars {chars} · cursor {row + 1}:{col + 1} · "
            f"longest line {tallest}ch · EN wrap {wrap}ch")

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
        it = self.current_item
        parts = [
            f"FILE  : {it.file}",
            f"ID    : {', '.join(it.ids) or '(no id)'}",
            f"SPEAKER: {it.speaker or '(none)'}",
            "EN:",
            it.en,
            "VN:",
            it.vn,
        ]
        self._clip("Item", "\n".join(parts))

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
        search = self.query_one("#search", Input)
        if self.screen.focused is search and search.value:
            search.value = ""
            if not self.dirty:
                self.current_key = None
            self.refresh_table()
            return
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
        except Exception:
            return
        key = table.get_row_at(idx)
        item = self.rows_by_key.get(key[0] + "\u0000" + key[1])
        if item is not None and self._suppress_highlight is False:
            self.load_item(item)

    def action_prev_item(self) -> None:
        self._step_item(-1)

    def action_next_item(self) -> None:
        self._step_item(1)

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
        slot = self.query_one("#inline_panel", Vertical)
        slot.remove_children()
        slot.add_class("hidden")
        self.query_one("#legend_sc").display = True
        self.action_focus_table()

    def action_open_replace(self) -> None:
        self.open_slot(ReplacePanel(self))

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
        new_compound, n_subs, warns = replace_in_compound(
            editor.text, rule["rx"], rule["repl"])
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
    def on_search(self, _event: Input.Changed) -> None:
        # debounced search: refresh only after the user stops typing. A longer
        # delay avoids firing while the user is still hunting for characters
        # (slow typing with pauses longer than the threshold).
        if self._search_timer is not None:
            self._search_timer.stop()
        self._search_timer = self.set_timer(0.6, self._debounced_search)

    def _debounced_search(self) -> None:
        if not self.dirty:
            self.current_key = None
        self.refresh_table()

    @on(Input.Changed, "#file")
    def on_file(self, event: Input.Changed) -> None:
        self.base = event.value.strip()
        if not self.dirty:
            self.current_key = None
        self.refresh_table()

    @on(Input.Submitted, "#file")
    def on_file_submit(self, _event) -> None:
        self.query_one("#table", DataTable).focus()


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
