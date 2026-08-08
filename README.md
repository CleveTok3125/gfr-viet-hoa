# GBFR Vietnam Translation (Vietnamese localization patch)

Community Vietnamese translation for **Granblue Fantasy: Relink**. The game is
run with **language = Korean (ko)**: the patch replaces the Korean text tables
with Vietnamese and redirects the Korean UI resources to their English
counterparts, so no English voice/story lock is lost.

## How it works

- `translations.json` is the single source of truth: a map of
  `file.msg -> { English source string : Vietnamese string }`.
- `data/system/table/text/ko/*.msg` and `data/system/table/scenario/ko/*.msg`
  are msgpack tables (`rows_`/`column_`). The patch rewrites `text_` values by
  exact-match against the table, then applies node-transform rules from
  `rules.json` (e.g. skillboard stat names).
- `*_tag.msg` files (one per text/scenario table, `ko/`) carry the dialogue
  highlight ranges used for name colours and voice/text sync. The stored
  `start_`/`end_` offsets are character indices **into the English string**,
  so every tag is remapped to the matching position in the Vietnamese text
  (`src/remap_tags.py`). The tuned tag tables are snapshotted into
  `tag_tuning.json` below, so `apply.py` recreates them (and their
  `data.i` sizes) directly — no per-install `remap_tags` run is needed and
  installs never depend on leftover on-disk tag state.
- `data.i` is the FlatBuffers index of the archive. The patch:
  - redirects every `ui/.../kor/...` entry to its `eng` counterpart
    (`FileToChunkIndexers` structs) so the game loads English UI assets, and
  - rewrites the declared `ExternalFileSizes` for every patched loose table so
    the size checksum stays consistent. This covers the translated `.msg`
    tables during `apply.py` and the remapped `*_tag.msg` tables during
    `remap_tags --fix-sizes`.

## Repository layout

```
translations.json      EN -> VI table (source of truth)
rules.json             stat_map + node-transform rules
TRANSLATION_NOTES.md   translation rules
decisions.json         highlight decisions, phrase form (written by tr_edit)
filelist.txt.gz        internal file paths (hash -> path), under data/
fonts.zip              Vietnamese font overrides (data/font/*), under data/
gfrpatch/              runnable module: python3 -m gfrpatch
apply.py               one-command patch for end users
build_patch.py         build a self-contained release zip
updater.py             diff the table against a newer game build
verify.py              hash-check patched files vs release manifest
rebuild_translations.py  regenerate the table from a patched install
update_filelist.py     fetch the latest file list from GBFRDataTools
tag_overrides.json     manual VN highlight ranges for hard-to-resolve tags
tag_tuning.json        tuned *_tag.msg snapshot (single source; apply recreates tags)
vendor/                bundled pure-Python deps (msgpack, flatbuffers)
src/                   engine, data.i handling, extraction helpers
src/remap_tags.py      remap *_tag.msg offsets to the VN text (--write --fix-sizes)
src/apply_decisions.py expand decisions.json phrases into tag_overrides.json ranges
src/tag_review.py      interactive review of unresolved highlight ranges
src/tag_tuning.py      dump/merge/write tag_tuning.json
src/tr_edit.py         interactive TUI editor for text + markers
src/tr_edit_core.py    editor data layer (compound strings, round-trip)
```

No external pip installs are needed; the bundled `vendor/` is used automatically.

## Usage

### End user: download the source and run it

Download this repository (GitLab **Code → Download source code** / Download
ZIP), extract it anywhere, then run the module from inside the folder — no
build step, no pip installs:

```bash
python3 -m gfrpatch                       # asks for the game folder, or:
python3 -m gfrpatch --game "C:\Games\Granblue Fantasy - Relink"
```

**Windows:** everything is pure Python (stdlib + bundled `vendor/`), so it
runs on Windows too — use `py -3` instead of `python3`:

```bat
py -3 -m gfrpatch
```

The tool asks you to type your game folder if `--game` is not given (it also
prints any install it auto-detected, as a hint). It backs up `data.i` and the
`ko/` text+scenario tables to `<game>/vietnam_backup/`, patches everything,
verifies every table still unpacks, and is **idempotent** (re-running reports
nothing to patch). Close the game before patching (running game files are
locked), then launch the game with language = Korean.

**Restoring the pristine game.** The first apply run stores the untouched
`data.i` (plus the ko/ tables) in `<game>/vietnam_backup/`. To undo a patch
and return the game to its original state:

```bash
python3 -m gfrpatch --game "<game>" --restore
```

This restores `data.i` from the backup and removes the loose files the patch
created (the materialized `ko/` tables, tuned `*_tag.msg` tables, and the
installed fonts). Sound/ui and every archive-only file are left untouched; a
later `apply.py` run rebuilds the patch from scratch.

**Rebuild from pristine.** Use `--rebuild` to return the game to its original
state, apply the patch again from scratch, and finish by writing a *fresh*
release manifest (instead of hash-verifying against the old one) — handy when
translations changed so references moved:

```bash
python3 -m gfrpatch --game "<game>" --rebuild
```

It requires the apply-time backup to exist (run a normal patch first); it
exits with code 2 otherwise.

**Launch the translation editor.** `gfrpatch` also serves as the launcher for
the interactive TUI editor:

```bash
python3 -m gfrpatch edit --game "<game>" --file text_scenario_030
```

**Re-apply protection.** If the install looks already patched (`data.i`
differs from the backup) `apply.py` aborts with a hint and asks for
`--force` to proceed anyway (safe: it is idempotent), or `--restore` to
revert. Use `--skip-backup` to skip both the backup and this check.

The dialogue highlight ranges live in `*_tag.msg`. They are remapped to the
Vietnamese text once, before a release is built, with
`python3 -m src.remap_tags --all --game "<game>" --write --fix-sizes` (this is
how the published zip and the manifests are produced; a maintainer only
re-runs it when the translation changes enough to shift offsets).

`--write` also recomputes the positional `dynamics_`/`formats_` markers
(the `<d>`/placeholder offsets the engine uses to strip tag markup) purely
from the translated text, including rows that have no English equivalent.
`--fix-sizes` is required: the game validates the declared `ExternalFileSize`
of every loose `_tag.msg` against disk, and `apply.py` only fixes the sizes
of the translated `.msg` tables. Without it the engine ignores a rewritten
tag table and renders literal `<d>` markers.

Ranges that are translated freely (e.g. `perfect dodge` → `né tránh hoàn hảo`)
cannot be located automatically. They are surfaced with
`--report review.json`, and each one is resolved interactively with
`python3 -m src.tag_review --game "<game>"`, which asks for the exact VN
range and stores the answer in `tag_overrides.json`. `remap_tags.py` applies
those overrides verbatim when `--overrides tag_overrides.json` is passed.

### Tag tuning source of truth: `tag_tuning.json`

`tag_tuning.json` is a git-tracked snapshot of the *tuned* `*_tag.msg` tables
(the TheRedTeam tune plus our Vietnamese remap), keyed per `id_`/`subid_`. It
is the single source of truth: `apply.py` writes every tag table from this
file during patching and fixes the declared `ExternalFileSizes`, so a fresh
install gets the exact tune without running `remap_tags` by hand.

Manual overrides are applied automatically: when patching, `gfrpatch` /
`apply.py` also load `tag_overrides.json`. For a row that has an override, the
override is **authoritative**: it replaces the baked-in tuned spans and any
tuned span key the override no longer defines is dropped, so stale/overlapping
highlights cannot linger behind an edit. Element metadata (`color_`,
`wordID_`, `type_`) is carried over from the tuned span at the same index, so
glossary links and colors survive. A highlight added in the TUI editor lands in
the game on the next patch run with no separate `remap_tags --overrides` step.

To (re)create the snapshot from a patched install:

```bash
python3 -m src.tag_tuning --game "<game>" --dump tag_tuning.json
```

To refresh only the entries that changed since the snapshot (a newer
translation or a new remap), merge a fresh dump over the file — untouched
entries keep their existing values:

```bash
python3 -m src.tag_tuning --game "<game>" --merge tag_tuning.json
python3 -m src.tag_tuning --game "<game>" --merge tag_tuning.json --write
```

`--write` also recreates the tables in the game and re-fixes their sizes.
When a tag is later fixed by hand, overwrite the affected `id_::subid_`
entry inside `tag_tuning.json`; everything else keeps working unchanged and
no old disk data is relied on.

Options: `--backup-dir <dir>`, `--no-ui`, `--no-fix-sizes`, `--skip-backup`,
`--force`, `--restore`. The `python3 -m gfrpatch` entrypoint accepts the same
options.

The plain `apply.py` script (with auto-detection) works identically.

**Supported builds:** the table is maintained for the latest game build. On an
*older* build the patch is still safe: it prints a `Build check: WARNING`, and
patches only the strings that match the table while leaving everything else
intact. For best results, always update the game to the supported build.

### No-Python users: pre-patched release zip

`build_patch.py` produces a zip containing `data.i` + the translated `ko/`
tables (text, scenario and their `*_tag.msg` files) with the game's exact
relative layout:

```bash
python3 build_patch.py --game "/path/to/install" --out gbfr_vietnam.zip
```

Extract the zip over the game directory (overwriting `data.i` and the `ko/`
tables). This is what gets published as a GitHub Release.

**Important:** the zip is built from one specific game build and should only
be applied to that exact build (check the `Build check` line when in doubt).
Applying a newer zip over an older install may break the game because `data.i`
indexes assets that the older build does not have. Prefer `apply.py` if you
are not on the exact build the zip was made for.

### Maintainer: refresh the translation when the game updates

```bash
python3 updater.py --game "/path/to/new/install"
```

The English sources are re-extracted from the new `data.i`; strings that still
match exactly keep their translation, strings within `difflib` ratio >= 0.95
are carried over automatically, and everything else lands in `review.txt`
for a human to confirm or translate. Review, merge, then rebuild the release
zip.

## Adding translations

Edit `translations.json` directly, or use the interactive TUI editor
(`tr_edit.py`, below) to work on the text together with its highlight markers.
Every key must be the exact English string as found in the game (extract it
with `src/extract.py` if unsure), the value the Vietnamese text. Keep proper
names, format placeholders (`{0}`, `<d>`), and credits/license text unchanged.
Run `apply.py` on a fresh English install to verify, then `build_patch.py` to
ship.

The table covers the 14 main text tables plus 53 battle-scenario dialogue
tables (`data/system/table/scenario/ko/*`). Scenario dialogue is based on the
base-game translation by **TheRedTeam** (before the Endless Ragnarok DLC);
see `meta.credits` in `translations.json`.

Follow the rules in `TRANSLATION_NOTES.md` when translating

### Editing with the TUI editor (`tr_edit`)

`src/tr_edit.py` is a full-screen editor (built on `textual`) for browsing
the table and editing each entry together with its dialogue highlight markers.
It is the only tool in this repo that needs a pip install (`pip install
textual`); the patch pipeline itself stays pure stdlib + bundled `vendor/`.
Run it from the repo root:

```bash
PYTHONPATH=src:vendor python3 src/tr_edit.py \
    --game "/path/to/install" [--file text_scenario_030]
```

Each entry is shown as a *compound string*: the Vietnamese text with inline
markers (conventions below). Saving (Ctrl+S) writes back to
`translations.json`, `decisions.json` and `tag_overrides.json` in one go.

Keys:

- Up/Down (or j/k) — move between items
- Ctrl+E — focus the editor
- Ctrl+S — save the current edit (writes all three JSONs)
- Ctrl+R — discard the current edit, reload from the saved state
- Ctrl+F — focus search (EN/VN/ID, case-insensitive, debounced, `*`/`?`
  wildcards; `\n` is treated as a space so a query typed with spaces matches
  text split across line breaks)
- Ctrl+L — focus the file filter (empty = browse all tables); Tab moves the
  focus across all five filter boxes (search, range, file, ID, Speaker)
- The index-range filter (e.g. `100-120`, a bare `100`, or an open-ended `100-`)
  sits next to the file filter. When it holds a range only those rows are
  listed, and the index column `N` shows the item's position in that table's
  enumeration
- ID and Speaker filter boxes in the filter bar: typing in them keeps only
  rows whose row id / speaker matches (the bar reads search - range - file -
  ID - Speaker, left to right)
- Ctrl+N — next table file
- Esc — back to the item list
- PageUp/PageDown — scroll the focused preview/legend panel
- F4 — toggle the EN preview between plain text and the game's highlight
  markers (`{c:}`/`{w:}`/`{b:}` plus the `{p}` player-name insertion point),
  to see which substrings the engine highlights
- F3 — auto-wrap the current editor text to the EN wrap width (the
  `EN wrap Nch` number shown in the stats): all existing line breaks are first
  joined into one flow, then the text is re-wrapped; highlight markers are kept
  intact and never split across lines
- Ctrl+T / Ctrl+J / Ctrl+G / Ctrl+O — copy VN (plain) / raw Japanese / EN /
  compound to clipboard
- Ctrl+M — copy just the current item's file or ID (pick one in an inline
  menu in the bottom-left panel)
- Ctrl+H — copy a full debug dump
- Ctrl+Up / Ctrl+Down — previous / next item (wraps around; the editor
  refuses to move away with unsaved changes)
- F2 — configure a regex search & replace rule for the session (pattern,
  replacement, match-case / whole-word options); it shows a live count and a
  live preview of the resulting text as you type, and saving keeps the rule in
  memory. The form is shown inline in place of the legend panel, so you can
  still switch items while it is open (the preview re-evaluates for the
  current item).
- F5 — apply the saved F2 rule to the text of the item currently open in the
  editor, immediately; markers stay aligned (phrases that disappear are
  reported as warnings). The change is not written until you press Ctrl+S.
- F8 — view context: jump the current item into its own table. It fills the
  file filter, clears the search, and sets the index-range filter to a small
  window (current index ± 15) so the item's row is always visible on screen
  without scrolling. The range box shows e.g. `135-165`; the notification
  reports the exact item index, and you can widen the range to read more
  context above/below
- F6 — edit the current item's voice-sync (`times_`) markers. The preview
  shows a `Sync:` line with each marker (`@offset` + wait time); F6 opens an
  inline panel with an editable offset per marker. Saving writes the offsets
  to `tag_overrides.json` (key `times_`), which the patch stamps onto the
  tuned tag tables — use it to fix a sync point by hand when the automatic
  remap lands slightly off.
- Ctrl+Q — quit

The preview panel highlights the current search query inside the plain VN text
(reverse video), shows the original Japanese (`JA (raw)`) below it for
kanji-exact reference, and the legend explains every marker. Both panels scroll
independently.

Marker conventions (self-defined; `tag_tuning.json` is intentionally left
untouched):

```
[Speaker]     read-only speaker prefix (scenario only); shown above the
              editor, auto re-added on save, never counted in the stats
{c:phrase}    colors_  highlight
{w:phrase}    words_   highlight
{b:phrase}    bolds_   highlight
{cw:phrase}   colors_+words_ on the same phrase
{p}           zero-width player-name insertion point
\{  \}  \\    escape a literal brace / backslash
```

Highlight decisions are stored in phrase form in `decisions.json` (VN phrase
per row id). `src/apply_decisions.py` expands them into the positional
`tag_overrides.json` ranges against an installed copy of the game; the editor
keeps both files in sync on every save. Highlights that exist only in the
game's tuned tag tables (never recorded in decisions/overrides) are also shown
in the editor so they can be reviewed and edited; once a row has an override,
that override is authoritative for its highlights.

## Operating this project (handover guide)

This section is a step-by-step runbook for whoever maintains the patch after
the original author. You only need Python 3 and a copy of the game; nothing
else is installed via pip.

### When the game updates

1. Get the newest game build (e.g. update via Steam).
2. Refresh the bundled file list from GBFRDataTools:

   ```bash
   python3 update_filelist.py
   ```

   (This downloads `filelist.txt` from the upstream GBFRDataTools project and
   packs it into `data/filelist.txt.gz`; you can also point `apply.py` at an
   external copy with `GBFR_FILELIST=/path/to/filelist.txt` instead.)
3. Diff the English sources of the new build against the table:

   ```bash
   python3 updater.py --game "/path/to/new/install"
   ```

   This writes `translations_new.json` (exact + auto-accepted fuzzy) and
   `review.txt`. Strings marked `[NEW]` need a human translation; `[REVIEW]`
   and `[ACCEPTED]` should be eyeballed.
4. Translate the `[NEW]` strings into `translations_new.json` (follow the
   existing style; keep proper nouns, `{0}` placeholders, and `<d>` codes).
5. Promote the reviewed table:

   ```bash
   mv translations_new.json translations.json
   ```

   (If you prefer, edit `translations.json` directly instead of step 3-5.)
6. Sanity-check against the new build:

   ```bash
   python3 apply.py --game "/path/to/new/install"
   ```

   Expect `Build check: WARNING` to disappear only after `build_fingerprint`
   matches the new build; if you rebuilt `translations.json` with
   `rebuild_translations.py`, the fingerprint is updated automatically.
7. Remap the dialogue highlight offsets to the new text and re-verify:

   ```bash
   python3 -m src.remap_tags --all --game "/path/to/new/install" \
       --report /tmp/tag_review.json
   python3 -m src.tag_review --game "/path/to/new/install"
   python3 -m src.remap_tags --all --game "/path/to/new/install" --write \
       --overrides tag_overrides.json --fix-sizes
   python3 verify.py --game "/path/to/new/install" --gen
   ```

   The first `remap_tags` pass reports every range it could not resolve
   exactly; `tag_review` walks you through them and fills in
   `tag_overrides.json`; the second `remap_tags` pass applies both the
   automatic remap and the manual overrides, and `--fix-sizes` rewrites the
   declared `ExternalFileSize` of every changed tag file in `data.i` (the
   game otherwise rejects tag tables whose size no longer matches). Without
   this, name highlights and voice/text sync would drift from the dialogue,
   and the engine would render literal `<d>` markers.
   For **incremental** manual highlights added later in the TUI editor, this
   full remap pass is not needed: `apply.py` / `gfrpatch` already stamp every
   entry of `tag_overrides.json` onto the recreated tag tables during
   patching.
8. Ship it: commit, then

   ```bash
   python3 build_patch.py --game "/path/to/new/install" --out gbfr_vietnam.zip
   ```

   and upload the zip as a release.

### Rebuilding the table from scratch (not normally needed)

If `translations.json` is lost or you want to regenerate it from an install
that already has the Vietnamese patch applied:

```bash
python3 rebuild_translations.py --game "/path/to/patched/install"
```

It diffs the English sources (extracted from `data.i`) against the installed
`ko/` tables and regenerates `translations.json` (with a fresh
`build_fingerprint`).

### Golden rules

- `translations.json` is the only source of truth; never edit game files by
  hand.
- Keep `build_fingerprint` in `translations.json` meta in sync with the game
  build you release for, or `apply.py` will warn.
- `apply.py` is idempotent and never touches your save data; running it on an
  outdated build is safe (new strings simply stay English).

## Known issues

- **"Anh" may still be used for The Captain.** The Captain is a
  gender-selectable protagonist (Gran/Djeeta). The original translation
  defaults to the masculine "Anh" when addressing the captain, so some
  dialogue lines may still read "Anh" even for a female captain. A pass
  over the scenario lines converted the bulk of these to "thuyền trưởng"
  (captain) or "bạn", and the speaker map in `data/scenario_speakers.json`
  plus the review script (`src/build_speaker_map.py`) make it possible to
  audit the rest; a few stragglers may remain.
- **Some pop-ups, waiting/loading screens lose their text.** Certain UI
  elements (pop-up prompts, wait dialogs, loading screens) can end up blank or
  missing text after the translation. This is under investigation; the cause is
  likely an offset/format mismatch specific to those table rows, similar to the
  `<d>` marker issue fixed for dialogue.
- **Some sections are not fully translated yet.** A number of strings are still
  untranslated (English or Korean text remains). These are tracked in
  `translations.json` and get filled in over time; run `updater.py` after a game
  update to surface the newest untranslated rows.
- **Button-icon placeholders can drift or fail to render.** When a string
  contains a button-icon token (e.g. a controller/gamepad key glyph), the icon
  may appear in the wrong position or not render at all. The tag remap handles
  `<d>` and `{placeholder}` markers, but icon tokens need a dedicated pass.
- **Voice sync / text-reveal timing.** Dialogue `*_tag.msg` tables carry
  `times_` markers (a character offset, a wait time and a wait flag) that pace
  the text-reveal against the spoken line. Their offsets index the original
  (English) string, so after translation they point at the wrong character and
  the reveal drifts from the voice. `src/fix_times_offsets.py` rewrites every
  `times_` offset to the matching position in the Vietnamese text (EN→VN char
  map), exactly like the highlight spans; run it with `--game <install>
  --write` after a big translation pass, then the tuned tags are already
  correct. Cosmetic — the wording itself is unaffected.
- **Residual highlight drift on heavily-translated terms.** Dialogue name
  highlights are driven by `*_tag.msg` character offsets, which are remapped
  to the Vietnamese text at patch time. For proper nouns that are kept
  verbatim the highlight lands exactly; when a term is translated freely
  (e.g. `perfect dodge` → `né tránh hoàn hảo`) the remap can only approximate
  the span, so a highlight may start one or two words off. Cosmetic only —
  the wording is unaffected.

## Disclaimer

Fan-made localization. All game assets and trademarks belong to Cygames, Inc.
This is a personal-usage mod; distribute only within private circles.

The scenario dialogue is based on the base-game translation by **TheRedTeam**
(before the **Endless Ragnarok** DLC); any additional or revised translations
beyond that base are machine/AI-generated. We take no responsibility for the
quality, accuracy or completeness of the AI-generated translations, and no
responsibility for maintaining this project going forward.
