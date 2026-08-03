# Changelog

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
