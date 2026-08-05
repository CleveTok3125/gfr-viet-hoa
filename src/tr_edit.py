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
    Esc               back to the item list
    Ctrl+Q            quit
"""
from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, ".."))

from textual.app import App, ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.widgets import (  # noqa: E402
    DataTable, Footer, Header, Input, Static, TextArea)
from textual.containers import Horizontal, Vertical  # noqa: E402
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
    "[b]Speaker[/b]  auto-prefix; edit text without it, it is re-added"
)


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
    #preview {
        height: 1fr;
        border: round $primary;
        padding: 0 1;
        overflow-y: auto;
    }
    #hint {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    #legend {
        height: 1fr;
        border: round $secondary;
        padding: 0 1;
        overflow-y: auto;
        color: $text-muted;
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
    """

    BINDINGS = [
        Binding("ctrl+s", "save_edit", "Save", show=True),
        Binding("ctrl+r", "reset_edit", "Reset", show=True),
        Binding("ctrl+e", "focus_editor", "Edit", show=True),
        Binding("ctrl+f", "focus_search", "Search", show=True),
        Binding("ctrl+l", "focus_file", "File", show=True),
        Binding("ctrl+n", "next_file", "Next file", show=True),
        Binding("escape", "focus_table", "List", show=True),
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

    # -- composition -------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            with Horizontal(classes="filters"):
                yield Input(placeholder="search EN / VN / ID (case-insensitive)",
                            id="search")
                yield Input(placeholder="file base (e.g. text_scenario_030)",
                            value=self.base, id="file")
            with Horizontal(classes="main"):
                with Vertical(classes="pane pane-left"):
                    yield Static("", id="preview")
                    yield Static("", id="hint")
                    yield Static(LEGEND, id="legend")
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
        # full repopulate, so select + load explicitly.
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

    def set_hint(self) -> None:
        n = len(self.items)
        scope = f"{self.base}.msg" if self.base else "all files"
        self.query_one("#hint", Static).update(
            f"{n} item(s) · {scope} · "
            "Ctrl+S save · Ctrl+R reset · Ctrl+F search")

    # -- selection / editor ------------------------------------------------

    @on(DataTable.RowHighlighted)
    def on_row(self, event: DataTable.RowHighlighted) -> None:
        table = self.query_one("#table", DataTable)
        if event.row_key is None or event.row_key.value is None:
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
        self.load_item(item)

    def load_item(self, item) -> None:
        self.current_key = (item.file, item.en)
        self.current_item = item
        ids = ", ".join(item.ids) or "(no id)"
        prev = (f"[b]{item.file}[/b]  {ids}\n"
                f"[b]EN:[/b]\n{item.en}\n"
                f"[b]VN (plain):[/b]\n{item.vn}")
        self.query_one("#preview", Static).update(prev)
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

    def action_focus_editor(self) -> None:
        self.query_one("#editor", TextArea).focus()

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_focus_file(self) -> None:
        self.query_one("#file", Input).focus()

    def action_focus_table(self) -> None:
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

    # -- filter inputs -----------------------------------------------------

    @on(Input.Changed, "#search")
    def on_search(self, _event: Input.Changed) -> None:
        # debounced search: refresh only after the user pauses typing
        if self._search_timer is not None:
            self._search_timer.stop()
        self._search_timer = self.set_timer(0.3, self._debounced_search)

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
