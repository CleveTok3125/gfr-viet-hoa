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
  (`src/remap_tags.py`).
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
filelist.txt.gz        internal file paths (hash -> path), under data/
gfrpatch/              runnable module: python3 -m gfrpatch
apply.py               one-command patch for end users
build_patch.py         build a self-contained release zip
updater.py             diff the table against a newer game build
verify.py              hash-check patched files vs release manifest
rebuild_translations.py  regenerate the table from a patched install
update_filelist.py     fetch the latest file list from GBFRDataTools
tag_overrides.json     manual VN highlight ranges for hard-to-resolve tags
vendor/                bundled pure-Python deps (msgpack, flatbuffers)
src/                   engine, data.i handling, extraction helpers
src/remap_tags.py      remap *_tag.msg offsets to the VN text (--write --fix-sizes)
src/tag_review.py      interactive review of unresolved highlight ranges
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

Options: `--backup-dir <dir>`, `--no-ui`, `--no-fix-sizes`, `--skip-backup`.

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

Edit `translations.json`. Every key must be the exact English string as found
in the game (extract it with `src/extract.py` if unsure), the value the
Vietnamese text. Keep proper names, format placeholders (`{0}`, `<d>`), and
credits/license text unchanged. Run `apply.py` on a fresh English install to
verify, then `build_patch.py` to ship.

The table covers the 14 main text tables plus 53 battle-scenario dialogue
tables (`data/system/table/scenario/ko/*`). Scenario dialogue is based on the
base-game translation by **TheRedTeam** (before the Endless Ragnarok DLC);
see `meta.credits` in `translations.json`.

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
- **Voice sync may drift in some dialogues.** Because the translated text is
  often shorter or longer than the original, lip-sync/voice timing can be off in
  a few scenes. This is inherent to text length changes and is cosmetic — the
  dialogue wording itself is unaffected.
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
