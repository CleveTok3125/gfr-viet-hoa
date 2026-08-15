# Changelog

## v0.8.0 - editor unified duplicate-row editing (2026-08-15)

- **Editor: unified duplicate-row editing.** Rows in the same table whose
  English text (exact 1-1) *and* source tag/times data match are grouped. A
  group member's ID is tinted cyan in the item table, with a red `*` prefix
  while its authored state still differs from the canonical member; hovering
  or focusing such a row shows the full group info in the preview, one
  aligned line per member: `✓/–  [↑][◎]  #index  ID  name  file`, where `✓`
  means the member's whole authored state (translation + highlight decisions
  + overrides incl. `{p}` and `times_`) equals the canonical member's, `↑`
  marks the canonical (whose VN the editor shows) and `◎` the row under the
  cursor. The editor always displays the group's shared VN, and Ctrl+S
  writes the edited VN + highlight markers to every member at once (and
  unifies `times_` when a member carries a manual voice-sync override); the
  F9 voice-sync panel edits the group's shared `times_` state and stamps
  every member's rids. A warning line flags groups whose members differ
  (saving will unify them). Grouping reads the English text from the game
  install, so it only applies when the editor runs with `--game`.
- **Editor: open an item straight from the command line.** `gfrpatch edit`
  (and `src/tr_edit.py`) pre-fill the filter boxes at launch: `--search`,
  `--id`, `--range` and `--speaker` join the existing `--file`, so a one-line
  command lands the item list directly on the rows you came to edit (the
  same filtering applies as if you had typed them).
- **Editor: voice-sync status column.** The item table gains a `TS (VN)`
  column next to EN showing the row's voice-sync state: `-` when the rid has
  no `times_` markers in the tuned tables, `auto` when it has them but no
  manual override yet (game default / auto pacing), and `edited` when a
  hand-fix exists in `tag_overrides.json` (via the F9 panel). It works
  without `--game` and refreshes right after an F9 save.
- **Patch: blank stored translations are never written into the game.** A
  row whose stored value is empty (or whitespace only) counts as "not
  translated": `final_text`, `PatchEngine.patch_file`,
  `patcher.patch_file_indexed` and `apply_diff` all fall back to the game's
  English reference instead of overwriting the row with an empty string.
- **Data: exact VN=EN and English-prose rows cleared.**
  `normalize_untranslated.py` empties any stored value that is not a real
  translation: exact matches of the English reference 1-1 (whitespace-
  normalized, case-sensitive -- safety first) and prose-length values with no
  Vietnamese diacritics that have a game English reference (these also drop
  encoding-corrupted copies of the English text, e.g. `\x81\x2c` for `↓`).
  EN source is the game install when given (`--game`) else the local
  `data/._en_prev.json` snapshot; `--write` applies, otherwise it reports.
  Because of the patcher change above the on-screen text is unchanged (or
  cleaned up), while the 89 cleared rows are honestly marked untranslated.
- **Editor: translation-state column + `@untr` filter.** A `TR (VN)` column
  reports each row as `-` (translated), `?` (blank value) or `EN`
  (prose-length text with no Vietnamese diacritics); the `@untr` token in the
  search box keeps only the untranslated rows (`?` / `EN`) and combines with
  any other words in the query (still matching EN/VN/ID), so a sweep like
  `@untr gran` lands on the untranslated rows mentioning "gran".
- **Repo layout: tools moved into `scripts/`.** The standalone command-line
  tools now live under `scripts/` (`python3 scripts/<name>.py`): `apply_diff`,
  `updater`, `rebuild_translations`, `update_filelist`,
  `normalize_untranslated`, `apply_decisions`, `build_font`,
  `build_speaker_map`, `fix_times_offsets`, `review_dump`, `tag_review`.
  `src/` is now the shared library layer (runnable utilities keep
  `python3 -m src.<name>`); retired/one-time tools sit in `tools/`
  (`fix_translations`, `convert_to_id_keys`, `verify_conversion`). The two
  end-user entrypoints stay where they are (`python3 apply.py`,
  `python3 -m gfrpatch`).

## v0.7.0 - EN redirect, voice-sync timing & Barlow font rebuild (2026-08-13)

- **Korean slot redirects to English first.** The patch copies the game's own
  English tables (`eng/*.msg`) over the Korean slot row-by-row, then applies
  Vietnamese translations on top (`src/patcher.py`); untranslated rows now
  show English instead of Korean. `apply_diff.py` mirrors the same two-stage
  order.

- **Font shipped under its OFL name only.** `data/fonts.zip` now carries a
  single built font as `font/barlow-medium.msg` + `font/barlow-medium_1.wtb`;
  the stock engine font names (`tt_pfdintextpro-*`, `fttk_yoongothic750`)
  no longer appear in the repository. At install time `patcher.install_fonts`
  writes that font under the engine's hardcoded font paths (English regular /
  medium and the Korean slot) with `pages.file` rewritten so each atlas
  resolves — those names exist on the installed game disk for engine lookup
  only and are never stored here. `verify.py` checks the engine paths to match.
- **Font assets are built from source, no game assets shipped.** The bundled
  `data/fonts.zip` (and `data/fonts_src/`) contains only build outputs of
  `src/build_font.py` from open-license typefaces — Barlow Medium (SIL OFL
  1.1) plus OFL/public-domain fallback subsets (DejaVu Sans, Noto Sans CJK).
  No glyph, metric, bitmap or name from the stock game fonts
  (`tt_pfdintextpro-*`, `fttk_yoongothic750`) is stored in this repository,
  and the documented rebuild command reproduces the shipped font byte-for-byte
  (same msg metrics, same 156-pair kern table, byte-identical `.wtb`).
- **Vietnamese letters flow at their base Latin width.** `src/build_font.py`
  normalizes the advance of precomposed/marked Latin letters (`ế`, `ỉ`, `ọ`,
  `ứ`, …) to their base letter's advance, so Vietnamese words no longer
  jitter wider/narrower than plain Latin text (Barlow ships `ỉ` ~34/1000
  narrower and `ọ` ~14/1000 narrower than `i`/`o`).
- **Font kerning kept non-negative for extra spacing.** `src/build_font.py`
  clamps GPOS kerning to `[0, 2]` (was `[-2, 2]`, originally `[-4, 2]`).
  Negative kern pulls every pair together and still looked cramped at this
  size, so 0 is now the loosest value (letters never sit closer than the
  vanilla spacing, gaining ~2px of air); only 156 positive kern pairs
  survive. Applied to all three installed font names (`regular`, `medium`,
  `fttk_yoongothic750`).
- **Glyph vertical position restored.** The previous build shifted every
  glyph up 3px on its quad (baseline-shift -3); that was reverted, so glyphs
  sit at the same height relative to the line as before.
- **Font source is Barlow Medium, not Roboto.** The shipped `data/fonts.zip`
  is regenerated from `data/fonts_src/Barlow-Medium.ttf` (SIL OFL 1.1) via
  `src/build_font.py`; Roboto was measured but did not match the stock
  metrics. The rebuild command in `README.md` reproduces the shipped font
  byte-for-byte (same msg metrics, same 156-pair kern table, byte-identical
  `.wtb`).
- **Fonts now match the game's real DDS format (DX10 BC4).** The rebuilt
  `data/fonts.zip` previously wrote RGBA8 atlases, which the game's BC4
  texture loader read with the wrong stride (each glyph sampled the wrong
  pixels -> stretched/mirrored/crooked glyphs). `src/build_font.py` now emits
  the same `WTB\0` v3 + DDS DX10 BC4_UNORM single-channel SDF layout the
  vanilla fonts use (flags `0xA1007`, `LINEARSIZE`, DXGI format 80), with a
  pure-Python BC4 encoder. Two more glyph-metric bugs were fixed alongside:
  `glyph_h` is now positive (it was `bottom - top` = always negative, which
  flipped/tautened the quads) and `advance` now includes the `2*padding` the
  game expects (`round(glyph_advance) + 12`), matching vanilla metrics.
- **Font rendering fixes in `src/build_font.py`.** (a) The BC4 encoder used a
  wrong 6-step palette formula (`(6-i)*r0+(i-1)*r1`); it now emits the standard
  BC4 palette `((8-i)*r0+(i-1)*r1)//7` that D3D hardware decodes with, so glyph
  shapes survive round-tripping (previously decode produced noise). (b) The
  baseline anchor used the hhea ascent, but PIL's `ImageDraw.text` places the
  baseline at the FreeType ascent (`ImageFont.getmetrics()[0]`, taller); the
  offset was ~9.5px too low, shifting every glyph up on its quad. Both are
  verified byte-decodable against the installed fonts.
- **Pre-patched release zip removed.** `build_patch.py` (which packaged a
  redistributable `data.i` + ko/ tables zip) has been removed from the
  repository. The translation is applied on your own install via
  `apply.py` / `gfrpatch` only; no pre-patched game files are shipped or
  generated. Speaker names in the editor now use Japanese (`name_ja`) as the
  fallback display below English (`name_en`), instead of Korean.
- **Vietnamese font rebuilt from Barlow (OFL) with fallback glyphs.**
  `data/fonts.zip` no longer ships the RedTeam-derived yoongothic glyphs.
  `src/build_font.py` regenerates the SDF bitmap fonts from Google Fonts'
  **Barlow Medium** (SIL OFL, source under `data/fonts_src/`), carrying ASCII /
  Latin-ext / Vietnamese (`U+1EA0`..`U+1EFF`, plus the precomposed `ĩ`/`ũ`
  at `U+0129`/`U+0169` that the 1EA0 block omits) under glyph ids computed as
  the UTF-8 bytes of each code point read as a big-endian integer (how the
  game's lookups work), with kerning from the font's GPOS tables. Glyphs the
  Barlow source lacks (arrows, stars, the full-width `（）`, `・`, `□`, etc.)
  are rasterized from OFL/public-domain fallback subsets
  (`data/fonts_src/fallback-*.ttf`, derived from DejaVu Sans and Noto Sans
  CJK, licenses bundled next to them). The fonts are built in the game's real
  atlas format (`2048x2048`, base 29, lineHeight 51) and installed under both
  the English names (`font/tt_pfdintextpro-{regular,medium}.msg` + `_1.wtb`)
  and the Korean names (`font/fttk_yoongothic750.msg` + `_1.wtb`), redirecting
  the game's Korean font slot to the patched English font. The previous font's
  Korean/Hangul glyphs are dropped — the patch targets the EN/VI UI. `apply.py`
  still installs the loose `data/font/*` overrides and registers their hashes
  in `data.i`; the font is built from source rather than redistributing the
  commercial glyphs.

- **Voice sync / text-reveal timing fixed.** The dialogue `*_tag.msg` tables
  carry `times_` markers (char offset + wait time) that pace the text reveal
  against the spoken line. Their offsets were computed against the original
  English string and were never remapped, so after translation they pointed at
  the wrong character (or past the end) and the reveal drifted from the voice.
  `remap_tags.py` now remaps `times_` offsets to the Vietnamese text like the
  highlight spans, and the committed `tag_tuning.json` snapshot has been
  regenerated (1101 markers across 15 scenario files). `src/fix_times_offsets.py`
  re-runs the same pass after future translation changes.
- **Engine pause convention documented.** `times_` markers index the first
  character *after* the pause: the reveal pauses between `offset-1` and
  `offset`, so a pause at punctuation index `P` is stored as `P+1`. The editor
  stats now show `offset to type` (the cursor's char index + 1) instead of a
  raw `before cursor` count, the preview tint sits on the pause char
  (`offset-1`), and 35 hand-fixed markers in `tag_overrides.json` that had been
  written "on" the punctuation (pausing a character early) were shifted by +1.
  The F9 sync panel still stores raw engine offsets.
- **Editor: manual voice-sync (`times_`) editing.** The preview now shows a
  `Sync:` line with the item's sync markers (`@offset` + wait time), and the
  new **F9** action opens an inline panel where each marker's offset can be
  edited by hand (e.g. when the automatic remap lands a sync point a word off).
  Saving writes the offsets to `tag_overrides.json` under the new `times_` key;
  `tag_tuning.write_to_game` stamps them onto the tuned tag tables at patch
  time (overrides keep the marker's `time_`/`wait_` values). While the F9
  panel is open, **↑/↓ nudge the focused marker's offset by one character at
  full key-repeat speed** (no throttling), and the pause point is highlighted
  live inside the editor — a debounced selection (same 0.15s debounce as the
  search box) sits on the pause char so you can drag a sync point into place
  visually without losing focus on the panel. The panel re-reads the tuned
  snapshot when the item changes and closes itself if the new item no longer
  has matching markers.
- **Editor: pause-char tint.** The exact character where a `times_` marker
  pauses the reveal is tinted on both the VN and the EN+ preview, so a
  hand-fixed sync point is visually confirmed in place. Out-of-range markers
  (a stale/preview offset past the end of the text) no longer crash the
  preview — the scan is clamped to the text length.
- **Editor: cursor char counter.** The status line now reports `before cursor
  Nch` (the plain-VN index — newlines counted — of the char right after the
  caret, matching the offset typed in the F9 sync panel) next to the word/char
  counts, with the editor stats on a dedicated line (auto-grown so the second
  line is never clipped). The counter maps the plain-VN index, skipping inline
  markers.
- **Editor: item index is per-table.** The N column and the range box now
  always show the row's position inside its own table, no matter how many
  files are listed, so a search result no longer shows a huge cross-database
  number and F8 (view context) reports the same index that is on screen.
- **Editor: shell-style autocomplete.** The file, ID and speaker filter boxes
  offer a tab-completable suggestion (Right accepts), sourced from the loaded
  table names / row ids / speaker set.
- **Editor: toasts above the footer.** Save confirmations and warnings now
  render just above the editor status line instead of overlaying the input
  area.

## v0.6.0 - rebuild workflow, editor launcher & inline panels (2026-08-06)

- **`gfrpatch --rebuild`.** Restores the install to its pristine state from the
  apply-time backup, applies the patch again from scratch, then writes a fresh
  release manifest (the same action as `verify.py --gen`) instead of
  hash-verifying against the old one — useful after translation changes shift
  references. Requires a backup (run a normal patch first) and exits with code
  2 otherwise.
- **`gfrpatch edit` subcommand.** Launches the interactive TUI translation
  editor (`src/tr_edit.py`) with optional `--game` / `--file`, so the patcher
  entrypoint also serves as the editor launcher.
- **Editor: replace-rule and option panels are inline, not pop-ups.** The F2
  search & replace dialog is no longer a modal screen; instead it renders
  inline in the bottom-left panel (replacing the legend while open). Because it
  lives in the normal app tree, you can keep navigating items while it is open,
  and the live preview re-evaluates for whichever item is current. A reusable
  inline-slot mechanism (`open_slot`/`close_slot` + `SlotMenu`) supports future
  option menus the same way.
- **Editor: Ctrl+M copies one field.** Ctrl+M opens an inline menu to copy just
  the current item's file, or just its ID (previously it copied the whole
  FILE/ID/SPEAKER/EN/VN block).
- **Editor: F8 views context by index range.** Fills the file filter with the
  current item's table, clears the search, and sets a new index-range filter
  (e.g. `100-120`) to a small window around the item (±15) so its
  row is always visible on screen without scrolling the whole table, keeping
  the item selected (no cursor jump). The notification reports the exact item
  index. The range can be widened to read more of the surrounding dialogue.
  A new `idx range` input sits left of the file filter and gates the table rows
  by their enumeration index (shown in the `N` column).
- **Editor: ID and Speaker filters.** Two new boxes on the right of the file
  filter bar (search - range - file - ID - Speaker) keep only rows whose row
  id / speaker match the typed text, combined with the existing search, file
  and range filters.

## v0.5.9 - captain/Dragon Knight scenes, session replace rule & JA reference (2026-08-06)

- **Translations.** Rewrote the **White Dragon Knights** gallant characters
  (Lancelot, Percival, Siegfried, Vane) and the Bluesky Knights / Seedhollow
  scenes, plus the Captain's Adept Arts (Bí Kỹ) skill descriptions and several
  character profiles. Standardized the per-scene address term to match the
  captain's role (`thuyền trưởng` vs `đội trưởng`). Highlight ranges
  (`tag_overrides.json`) updated for the edited rows and
  `data/release_manifest.json` regenerated.
- **TUI editor: session regex replace rule (F2/F5).** F2 opens a dialog where
  you type a regex pattern, replacement and case/whole-word options; a live
  count and a live preview of the resulting text update as you type. Saving
  keeps the rule in memory for the session. F5 applies the rule to the editor's
  current text immediately, re-anchoring highlight markers (phrases that
  disappear are reported as warnings); the edit is only written on Ctrl+S.
- **TUI editor: quick navigation.** Ctrl+Up / Ctrl+Down move to the previous /
  next item (wraps around; refuses to move away with unsaved changes).
- **TUI editor: raw-Japanese reference (Ctrl+J).** Copies the original Japanese
  row for the current item to the clipboard, and the preview now also shows the
  raw Japanese (`JA (raw)`) beneath the English for kanji-exact reference.
- **Translation notes.** Added `TRANSLATION_NOTES.md` (written in Vietnamese) as
  the reference for translation rules, terminology and the captain address-term
  policy; linked from the README.

## v0.5.8 - translation polish for the Eternals arc (2026-08-06)

- **Eternals arc scenes rewritten.** Dialogue quality improved across the
  chapters **A Trial of Two Eternities**, **Ragnalia, the Heralds of Doom**
  and **Becoming Fatebreakers** (`text_scenario_720` + chapter summaries in
  `text_story`): address terms between the Eternals and the crew, punctuation,
  line-break balance and phrasing were reworked; highlight ranges
  (`tag_overrides.json`) updated to match, and `data/release_manifest.json`
  regenerated for the touched tables.

## v0.5.7 - editor UX, authoritative overrides & Conflux translation (2026-08-06)

- **`tag_overrides.json` is authoritative for edited rows.** A highlight range
  saved from the editor replaces the baked-in tuned span for that row, and any
  tuned span key the override no longer defines is dropped instead of lingering
  behind it — no more stale/overlapping highlights. Element metadata
  (`color_`, `wordID_`, `type_`) is carried over from the tuned span at the
  same index, so glossary links and colors survive.
  `src/tag_tuning._apply_overrides` implements the replacement; the editor's
  `_load_markers` stops resurrecting tuned spans for a row that has an override.
- **TUI editor UX.** Longer search debounce (0.6s) so the list only refreshes
  after you stop typing; preview & legend are scrollable panels
  (`ScrollableContainer`, PageUp/PageDown/scroll wheel) with visible
  scrollbars; tuned-game highlights that were never edited now show up in the
  editor instead of being hidden behind stale ranges.
- **Translation report.** Terminology unified (`Skyfarer` → `Phi Hành Giả`,
  `skydweller` → `cư dân bầu trời`), glossary entries `Wedge`/`Pseudo-Wedge`
  gained TL notes explaining the meaning, the **Into the Conflux** chapter
  dialogue (`text_scenario_720`) was revised (address term, name formatting,
  clearer phrasing), and other glossary/profile strings were polished.
  `data/release_manifest.json` regenerated for the changed tables.

## v0.5.6 - manual tag overrides flow through the patcher (2026-08-06)

- **`tag_overrides.json` now flows through `gfrpatch`/`apply.py`.** The
  manual highlight ranges added in the TUI editor are stamped onto the
  `*_tag.msg` tables when the patcher recreates them from `tag_tuning.json`,
  so a fresh install (or a re-apply) picks up every manual override
  automatically - no separate `remap_tags --overrides` run needed.
  `src/tag_tuning._apply_overrides` merges ranges by `id_`, extending the
  tag set when an override points past the current span list (e.g. an added
  player-name placeholder), and the stamp count is reported by the patcher.

## v0.5.5 - interactive editor for text & markers (2026-08-05)

- **New TUI editor.** `src/tr_edit.py` (built on `textual`; the only tool in
  the repo that needs a pip install) browses the table and edits each entry
  together with its dialogue highlight markers; `src/tr_edit_core.py` holds
  the UI-free data layer. Each item renders as a *compound string* (VN text
  with inline markers) and Ctrl+S round-trips it back into the three
   authoring files at once: `translations.json`, `decisions.json`
   (now `highlight_decisions.json`), `tag_overrides.json`.
- **`decisions.json` authoring layer** (now `highlight_decisions.json`). Highlight decisions are stored in
  phrase form (VN phrase per row id) next to the positional
  `tag_overrides.json`; `src/apply_decisions.py` expands phrases into
  positions against an installed copy, and the editor keeps both files in
  sync on every save.
- **Marker conventions.** `{c:}`/`{w:}`/`{b:}`/`{cw:}` highlight markers and
  `{p}` player-name insertion point (literals escaped as `\{` `\}` `\\`).
  The speaker prefix `[Speaker]` is shown read-only above the editor, is
  auto re-added on save, and is excluded from the text stats.
  `tag_tuning.json` is intentionally left untouched.
- **Editor features.** Case-insensitive debounced search (EN/VN/ID), file
  filter with an empty default (= browse all tables), per-row FILE column,
  live stats (words/chars, cursor position, longest line, EN wrap
  reference), and a non-destructive `self_test` round-trip.

## v0.5.4 - pristine installs, tag tuning & restore (2026-08-04)

- **Pristine-install support.** `apply.py` now materializes the archive-only
  `ko/` tables into loose files (`src/datai.materialize_loose` +
  `src/patcher.loose_ko_paths`) so the patch works on a clean game that has
  no `data/system/table` directory on disk, and registers their hashes in
  `data.i`. Manifest regenerated (180 files).
- **Tuned tag tables as source of truth.** The tuned `*_tag.msg` tables are
  snapshotted into the git-tracked `tag_tuning.json` (88 files, keyed per
  `id_`/`subid_`); `apply.py` recreates every tag table from it and fixes the
  declared `ExternalFileSizes`, so a fresh install no longer depends on
  leftover on-disk tag state. `src/tag_tuning.py` provides
  `--dump`/`--merge`/`--write`.
- **Selective tag remap.** Only tag ranges that still carry raw English
  positions (files the exe patch left untranslated) are re-remapped from the
  EN ground truth; already-tuned ranges and `names_` are preserved unchanged.
  This fixes wrong highlights (e.g. `Zegagrande` in `text_scenario_730`
  showing as "ande vậy.") across ~20 untranslated files, with 0 out-of-bounds
  spans on all 6414 rows. `tag_overrides.json` extended with 3 manual ranges.
- **Restore & re-apply protection.** `apply.py --restore` returns the game to
  its pristine state from the auto-created `vietnam_backup/` (restores
  `data.i`, removes materialized tables, tuned tag tables and installed
  fonts). Applying onto an already-patched install is now blocked with a
  prompt for `--force` (idempotent re-apply) or `--restore`; `--skip-backup`
  bypasses both.
- **Speaker map tooling.** `src/build_speaker_map.py` builds
  `data/scenario_speakers.json` (per-scenario speaker map used to decide the
  Vietnamese address term for the gender-selectable Captain), annotates every
  review context line with its speaker, and makes that annotation optional.
- **Dialogue/HUD fixes.** Captain addressed as "thuyền trưởng" (remaining
  "Anh" uses documented); "Defeated" HUD label no longer reads "Thất Bại";
  in-battle level HUD uses "Lvl"; "Absolute Zero" fixed as "Độ Không Tuyệt
  Đối" (tracking `text_chainburst`).

## v0.5.3 - bundle Vietnamese fonts (2026-08-04)

- Bundled the 3 Vietnamese font files (`font/fttk_yoongothic750.{msg,_1.wtb,_2.wtb}`)
  into `data/fonts.zip` so the patch is self-contained. The stock `yoongothic`
  font in the game archives lacks the glyphs to render Vietnamese, so these
  loose `data/font/` overrides are required for correct in-game display.
- `apply.py` now installs the fonts as loose files and registers their hashes
  in `data.i` ExternalFileHashes/ExternalFileSizes, so the game loads the
  loose font instead of the archive one (same mechanism as the ko/ tables).
  Idempotent: existing files are left alone.
- `build_patch.py` and `verify.py` now include the fonts in the release zip
  and the reference manifest (140 files, 0 mismatches).

## v0.5.2 - literal `<d>` marker fix (2026-08-03)

- Fixed literal `<d>` markers rendering in dialogue/pop-up text. The tag
  remapper only rewrote the `bolds_/colors_/words_/names_` ranges, leaving the
  `dynamics_`/`formats_` positional markers at their English offsets, so after
  translation the engine no longer recognized the `<d>` markup and printed it
  verbatim.
- `remap_tags.py` now recomputes `formats_`/`dynamics_` purely from the
  Vietnamese text (`formats_` = expanded placeholder end; dtag 24/28/29 = `<d>`
  positions; dtag 16/17 = color region; dtag 4/26 = `<d>` after placeholder),
  including rows with no English equivalent.
- New `remap_tags --fix-sizes` rewrites the declared `ExternalFileSize` of
  every changed `*_tag.msg` in `data.i`. The game validates loose-file sizes
  before loading them, and `apply.py` only fixed the translated `.msg` tables,
  so rewritten tag tables were silently ignored — the actual cause of the
  literal `<d>` markers.
- Re-verified `verify.py` (135 files, 0 mismatches).

## v0.5.1 - factual fixes for DLC rows (2026-08-03)

- `text_tutorial.msg`: fixed 90 rows that were scrambled after the Endless
  Ragnarok DLC (content landed on the wrong row, including one row outside the
  DLC block) and added 18 fresh translations for newly-added rows.
- `text_badge.msg`: fixed 71 factual errors — "3 Skybound Arts" read as "30",
  "1 time"/"2 times" defeat counts read as "3"/"2 lần", "10 min" read as "5",
  "3 loadout sets" read as "3", and several DLC badges swapped Tweyen/
  Sandalphon/Seofon names; also dropped a stray "thuyền" prefix.
- `text.msg`: fixed Narmaya's parry skill description where the character name
  had been mistranslated as Yodarha.
- Rebuilt `translations.json`, re-ran tag remapping and `verify.py` (135 files,
  0 mismatches) after every table change.

## v0.5.0 - translation quality pass & portable tool (2026-08-03)

- Fixed ambiguous stats: `ATK↑`/`ATK↓` and `DEF↑`/`DEF↓` were both rendered
  as "T.CÔNG"/"P.THỦ" (lost the up/down distinction); `Max HP↓` kept its
  arrow, `DMG↓` was no longer mistranslated as an ATK reduction, and
  `Skill Healing Cap Up` split from `Healing Cap Up`.
- Repaired 226 mojibake entries (arrows ↑/↓, ★/☆, curly quotes, fullwidth
  parens, ・, °) that displayed as corrupted characters; 268 rows fixed on
  disk.
- Restored em-dashes stored as "?" (218+ entries) and standardized the
  legacy short forms "T.CÔNG"/"P.THỦ" to "Tấn Công"/"Phòng Thủ".
- Added `gfrpatch/` module (`python3 -m gfrpatch`) which asks the user for
  their game folder instead of guessing - the supported distribution is
  simply downloading the source and running the module directly (no build
  step, no pip installs).
- CI pipeline removed.

## v0.4.0 - scenario dialogue coverage (2026-08-02)

- Pipeline now covers the 53 battle-scenario tables
  (`data/system/table/scenario/ko/*`) in addition to the 14 main text tables;
  `translations.json` grows to 35,266 EN->VI rows across 67 files.
- `apply.py`/`build_patch.py`/`verify.py` handle both table directories via a
  shared `table_rel()` mapping; `build_patch.py` release zips and the hash
  manifest now include the scenario tables.
- Scenario dialogue based on the base-game translation by **TheRedTeam**
  (before the Endless Ragnarok DLC); credited in `translations.json`
  meta.credits.
- `verify.py` added: md5 checks all patched files against
  `data/release_manifest.json` to detect a broken patch before launch.
- Added game-version detection (`src/game_version.py`) and a build
  fingerprint check so the tool warns when an install does not match the
  translation build.

## v0.3.0 - pipeline release (2026-08-02)

- Repository restructured as a maintainable pipeline:
  - `translations.json` rebuilt from a full diff of the installed tables vs the
    archived English sources (17,710 rows, 14 files) and verified to reproduce
    the on-disk Vietnamese patch (26938 rows compared, 98.8% identical; the
    remainder are context conflicts resolved by most-common choice).
  - `apply.py` rewritten around a shared `src/patcher.py` core.
  - `build_patch.py` produces a self-contained release zip (data.i + ko/
    tables), verified byte-for-byte against the patched install.
  - `updater.py` + `src/extract.py` re-extract English sources from a newer
    data.i and diff them against the current table (exact / fuzzy >=0.95 /
    review), outputting `translations_new.json` + `review.txt`.
  - Pure-Python XXH64 implementation matches the reference `xxhsum` vectors;
    bundles msgpack (pure fallback), flatbuffers, lz4.

## v0.2.0 - full table pass (2026-07-28)

- Translated and applied all remaining text tables: text_story, text_note
  (+ reversed story-letter rows), text_status, text_skillboard (node regex
  transform), text_limit_bonus, text_tutorial, text_badge, text_fate_episode,
  text_stage, text_dialog, text_communication, text_uskill.
- External-file size records in data.i rewritten for every patched table
  (0 mismatches after re-check).

## v0.1.0 - first playable patch (2026-07-xx)

- Replaced the Korean text tables (`text_ui`, `text.msg` weapon/item lines,
  quest names, tips) with Vietnamese.
- Redirected `ui/.../kor/...` archive entries to `eng` (423 entries) so UI
  assets load in English while text displays Vietnamese.
- Fixed missing text caused by loose-file size mismatches in data.i.
