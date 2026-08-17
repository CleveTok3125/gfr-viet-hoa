# GBFR Vietnam Translation (Vietnamese localization patch)

Community Vietnamese translation for **Granblue Fantasy: Relink**. Run the game
with **language = Korean (ko)**: the patch replaces the Korean text tables with
Vietnamese and redirects the Korean UI resources to their English counterparts,
so no English voice/story lock is lost.

## Contents

- [How it works](#how-it-works)
- [Repository layout](#repository-layout)
- [Usage](#usage)
  - [End user: download the source and run it](#end-user-download-the-source-and-run-it)
  - [Note on pre-patched distributions](#note-on-pre-patched-distributions)
  - [Fonts](#fonts)
- [Known issues](#known-issues)
- [Disclaimer](#disclaimer)
- [Maintainer docs](#maintainer-docs)

## How it works

This patch redirects the game's Korean slot to English first — the UI assets
and every text table — then overwrites Vietnamese onto that English base, so
untranslated rows stay English rather than Korean, and you keep the English
voice track and story. Everything is applied automatically by `gfrpatch` to
your own game install — there is no build step. Rows are matched by their
stable engine id, so the repository stores **no English (or Korean) game
text** — English is read from your own game at patch time. The mechanics are
explained in [`CONTRIBUTING.md`](#maintainer-docs).

## Repository layout

| What | Files |
|------|-------|
| Tool (code you run) | `gfrpatch/` · `apply.py` — runs the patch |
| Translation data (json) | `translations.json` (id-keyed), `highlight_decisions.json`, `tag_overrides.json`, `tag_tuning.json` |
| Font / pre-built files | `fonts.zip` + `data/` (contains pre-built artifacts) |
| Docs | `README.md` · `CONTRIBUTING.md` · `TRANSLATION_NOTES.md` |

## Usage

### End user: download the source and run it

Download this repository (GitLab **Code → Download source code** / Download
ZIP), extract it anywhere, then run the module from inside the folder — no
build step, no pip installs required (third-party libs ship as pure-Python
fallbacks in `vendor/`; pip installs of the pinned builds are used when
present and just make the hot paths faster):

```bash
python3 -m gfrpatch                       # asks for the game folder, or:
python3 -m gfrpatch --game "C:\Games\Granblue Fantasy - Relink"
```

The interactive editor additionally needs `textual` (no bundled fallback):

```bash
python3 -m pip install -r requirements-optional.txt
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

**Re-apply protection.** If the install looks already patched (`data.i`
differs from the backup) `apply.py` aborts with a hint and asks for
`--force` to proceed anyway (safe: it is idempotent), or `--restore` to
revert. Use `--skip-backup` to skip both the backup and this check.

**Launch the translation editor.** `gfrpatch` also serves as the launcher for
the interactive TUI editor:

```bash
python3 -m gfrpatch edit --game "<game>" --file text_scenario_030
```

The editor pre-fills its filter boxes from the command line, so a single
command can land on the rows you want to review — e.g. `--id SNT_WD720020_0320`
fills the ID box, `--search "<text>"` the search box, `--range 100-120` the
index range and `--speaker "<name>"` the speaker box (any combination works).

The full editor key reference is in [`CONTRIBUTING.md`](#maintainer-docs).

**Supported builds:** the table is maintained for the latest game build. On an
*older* build the patch is still safe: it prints a `Build check: WARNING`, and
patches only the strings that match the table while leaving everything else
intact. For best results, always update the game to the supported build.

### Note on pre-patched distributions

This project intentionally does **not** ship pre-patched game files (`data.i`,
patched `.msg` tables, fonts or any other build artifact) and provides no tool
to package one. Applying the translation always runs on your own install via
`apply.py` / `gfrpatch` above. Please do not re-upload patched game files
elsewhere — point people to this repository instead.

### Fonts

The patch ships a Vietnamese font regenerated from **Barlow Medium** (SIL Open
Font License 1.1) — open-license only, **no game assets** — and installs it
automatically onto the three engine font slots. To rebuild or tweak it, see
[`CONTRIBUTING.md`](#maintainer-docs).

## Known issues

- **"Anh" may still be used for The Captain.** Some lines may still read "Anh"
  even for a female captain; the bulk were converted to "thuyền trưởng"/"bạn".
- **Some pop-ups / loading screens lose their text.** Certain UI prompts can
  end up blank or missing after translation (under investigation).
- **Some sections are not fully translated yet.** A number of strings remain
  English/Korean and are filled in over time.
- **Button-icon placeholders can drift or fail to render.** Controller/gamepad
  key glyphs may appear misplaced or not render.
- **Voice sync / text-reveal timing.** On some lines the text reveal may drift
  slightly from the spoken voice. Cosmetic only.
- **Residual highlight drift on heavily-translated terms.** A name highlight
  may start a word or two off when a term is translated freely. Cosmetic only.

## Disclaimer

Fan-made localization. All game trademarks belong to Cygames, Inc. This is a
personal-usage mod. The repository ships **no game assets or extracted game
content** — the patch operates on your own installed copy at runtime. For the
full copyright and license scope, see [`NOTICE`](NOTICE).

**Requirements & legality.** This patch only works on a copy of the game you
own. It does not bypass DRM, does not ship or extract any game assets into the
repository, and does not patch cracked/illegitimate copies: the build
fingerprint check expects a genuine, unmodified English `data.i`, and the
translation writes into your own loose table files.

**Redistribution (GPL v3).** The project's **source code** and the
**file format, structure and tool-generated characteristics of the
translation data** are licensed under the **GNU GPL v3** (see `LICENSE` and
`NOTICE`). The translated content is not licensed, and the bundled fonts keep
their OFL licenses. Pre-built release artifacts (patched `.msg` tables,
`data.i`, fonts, release zips) are fan-mod outputs for personal use on your
own copy and fall outside this project's license grant. Prefer linking to this
repository so everyone always gets the source.

**Translation quality.** Only the strings reported as *hand-edited* (see
`TRANSLATION_NOTES.md` and the per-table progress marks) have been reviewed
and revised manually. Apart from the base-game content, everything else is
machine/AI-translated; we make **no quality guarantee** for it — it may
contain errors, awkward wording or mistranslations. We do not take
responsibility for the quality, accuracy or completeness of the
machine-translated sections, nor for maintaining this project going forward.

The scenario dialogue is based on the base-game translation by **TheRedTeam**
(before the **Endless Ragnarok** DLC).

## Maintainer docs

Deep-dive, handover runbook, full font build details, the complete TUI editor
reference and the technical explanation of every known issue live in
[`CONTRIBUTING.md`](CONTRIBUTING.md).
