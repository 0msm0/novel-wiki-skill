---
name: novel-wiki
description: Builds and keeps up to date a fan-wiki for a novel being written episode by episode, like the Naruto, Star Wars or Tolkien wikis. It reads each new or revised chapter and updates character, location, faction, item, lore and event pages, plus an episode guide, timeline, glossary, mysteries tracker and search, as a static HTML site in the project with a history log of every run. Use when the user says update wiki, build or refresh the wiki, sync the wiki with the new chapter, add episode N to the wiki, make a fandom or lore wiki or story bible site, or asks to correct a wiki page, even without saying novel. Not for Wikipedia lookups or a code project's docs wiki.
license: MIT
compatibility: Needs file access and Python 3.8+ (standard library only, no network). Built for Claude Code; also works in Claude.ai and the API where code execution is enabled.
metadata:
  author: novel-wiki contributors
  version: 1.0.0
  category: creative-writing
  tags: [fiction, worldbuilding, wiki, static-site, story-bible]
---

# Novel Wiki

Keep a living fan-wiki for an ongoing novel. Each run reads the episodes that
are new or changed since last time, extracts what they establish, merges it into
the wiki database and re-renders a static HTML site the author can open locally
or publish anywhere (GitHub Pages, Netlify, any web host).

The split of work: **you** do the reading and the editorial judgment and write
one JSON patch per episode. The bundled engine `scripts/wiki.py` does all the
bookkeeping deterministically (merging, rolling back revised episodes,
cross-links, backlinks, appearance lists, the site, the history log). Never
hand-edit `data/wiki.json` or the generated HTML; they are rewritten every run.

Run the engine as `python "${CLAUDE_SKILL_DIR}/scripts/wiki.py" --wiki <wiki-dir> <command>`
(use `python3` if `python` isn't found; if `${CLAUDE_SKILL_DIR}` isn't expanded,
use this skill's directory). Commands: `init`, `scan`, `brief`, `show`, `apply`,
`forget`, `build`, `log`, `check`. Run with `-h` for options.

## Layout it creates

```
<project>/wiki/
  wiki.config.json      title, episode file globs, label ("Episode"/"Chapter"), accent colour
  WIKI-HISTORY.md       human-readable log of every run (also at site/history.html)
  custom.css            optional, author's theme overrides (copied into the site)
  data/wiki.json        canonical database (engine-owned; wiki.json.bak = previous version)
  data/history.json     run log (engine-owned)
  data/patches/         one archived patch per episode = audit trail of what was extracted
  site/                 the publishable wiki: index.html, episodes, category/*, wiki/*, timeline,
                        glossary, threads (mysteries), all-pages, history, search
```

## Workflow

Track these steps; the run log at the end needs them.

### 1. Find or create the wiki

Glob for `**/wiki.config.json` (skip `node_modules`, `.git`). If one exists, its
folder is the wiki dir. Otherwise set one up:

- Find the manuscript: look for folders like `chapters/`, `episodes/`,
  `manuscript/`, `book/`, `drafts/`, and numbered `.md`/`.txt` files. Read
  `CLAUDE.md`, a README or an outline if present for the title and layout.
  Exclude notes, outlines, summaries and other non-prose files from the globs.
- Choose the label the author uses (Episode, Chapter, Part).
- Only ask the user if it is truly ambiguous which files are the story (for
  example a `drafts/` and a `final/` copy of the same chapters). Otherwise
  decide and say what you chose.
- `init --title "..." --globs "chapters/*.md" --label Chapter` with
  `--wiki <project>/wiki`. Add `--tagline`/`--author` if known.
- Read `references/wiki-style.md` before writing the first patch. It defines
  what gets a page, the article templates per type, and the canon rules.

### 2. Scan

`scan` lists every episode file as `NEW`, `CHANGED` (revised since it was
processed), `OK` or `MISSING` (file gone). Process NEW and CHANGED in reading
order. If the user named specific episodes, do just those.

If nothing is pending: run `build`, record the run with `log` (step 6), and tell
the user the wiki is already current.

For `MISSING`, ask before running `forget --episode N`; the author may have just
renamed the file (then fix `episode_globs` or the patch `source` instead).

### 3. Load what the wiki already knows

Run `brief`. It lists every entity id, name, alias, importance and appearance
span, open threads, glossary terms and recent episode summaries. Reusing these
ids is what keeps the wiki coherent; a new id for an existing character creates
a duplicate page.

### 4. Read each episode and write its patch

For each pending episode, in order:

1. Read the **entire** episode file. Do not skim or sample; small details (a
   scar, a surname, a date) are exactly what wiki readers look up.
2. List everything named in it. Match each to an existing id by name and
   aliases (titles, nicknames, partial names). Create new ids only for things
   that are genuinely new and pass the "what gets a page" bar.
3. For existing entities this episode develops, `show <id> ...` to get their
   current record, then write **rewritten** sections/lead/infobox values that
   integrate the new facts. Sections are replaced wholesale on merge.
4. Write the patch to `<wiki>/data/patches/ep-NNNN.json` (zero-padded number).
   Format, field rules and an example: `references/patch-format.md`. Read it the
   first time in a session. Essentials:
   - `episode`: number, title, `source` exactly as scan printed it, pov,
     summary, multi-paragraph synopsis.
   - `entities`: every page this episode touches, each with `presence`
     (`appears`, `pov`, `mentioned`) and a `history` entry of what happened to it
     **in this episode**.
   - `timeline`, `glossary`, `threads` (mysteries, set-ups, payoffs).
   - Link with `[[id]]`, `[[id|text]]`, `[[ep:N]]`, `[[glossary:Term]]`.
5. Validate with `apply --dry-run --patch <file>`. Fix every warning: a link
   to a missing id means create that entity or correct the id.
6. Apply it (step 5 below) **before reading the next episode**, so the next
   `brief`/`show` sees this episode's pages. State is saved after every apply,
   so an interrupted backlog resumes cleanly at the next `scan`.

For a CHANGED episode, write a complete fresh patch for it (not a diff). The
engine rolls back everything that episode contributed before applying the new
one. If the revision changes a fact that sections or leads state, rewrite those
too. Compare the revision with later episodes: if it now contradicts them
(someone captured in the old version is free in the new one, but a later
episode still treats them as captured), record it under `warnings` in the run
log and tell the author. Don't "fix" the later episode's pages to hide it.

### 5. Apply and check

Before each apply, write the run log (step 6) as it stands to
`<wiki>/data/last-run.json` (cumulative is fine; repeated lines are merged). The first apply of this request creates the
history entry; every later apply for the same request adds `--continue-run`,
which folds it into that entry (new steps, files and pages are merged in):

```
apply --patch <wiki>/data/patches/ep-0007.json --run-log <wiki>/data/last-run.json
apply --patch <wiki>/data/patches/ep-0008.json --run-log <wiki>/data/last-run.json --continue-run
check
```

`apply` merges, archives the patch, rebuilds the whole site, and records the
run in `data/history.json`, `site/history.html` and `WIKI-HISTORY.md`, adding
its own step line with page and warning counts. `check` reports broken links,
pages without a lead, and names or aliases shared by two pages (likely
duplicates). Fix real problems by correcting and re-applying the episode
patch (with `--continue-run`) or with an editorial patch (below).

### 6. The run log

The user wants to be able to see exactly what each run did, so make the run
log specific:

```json
{
  "request": "<the user's words>",
  "mode": "first build | incremental update | revision | correction | rebuild",
  "looked_at": ["every file and command output you consulted: config, each episode file, brief, show <ids>, outline/notes"],
  "steps": ["one line per step you actually performed, with counts"],
  "decisions": ["judgment calls: merges, renames, contradictions found, things skipped and why"],
  "warnings": ["anything the author should double-check, e.g. continuity slips"]
}
```

Steps and files are lists of what you have done so far; you don't need to
predict the apply result, the engine logs that. It also adds the timestamp,
episodes processed and the pages created, updated and removed. For a run that changes no data (nothing new, rebuild only),
use `log --run-log <file>` instead of `apply`.

### 7. Report

Tell the user briefly: which episodes were processed, how many pages were
created and updated (name the important new ones), threads opened or resolved,
any continuity issues worth their attention, and the path to
`<wiki>/site/index.html`. On the first build, add one line on publishing: the
`site/` folder is self-contained static HTML, so they can open it directly or
upload it to any static host.

## Other requests

- **Correct or change a page** ("Mira is 19, not 17", "merge Grey Man into
  Seren", "make Tobin a major character"): the author's word wins over the
  text; it's their world. Write an editorial patch,
  `{"editorial": true, "entities": [...]}`, save it as
  `<wiki>/data/patches/editorial-YYYYMMDD-HHMM.json` and apply it with a run
  log. Before writing it, Grep `<wiki>/data/wiki.json` for the old fact: it is
  often repeated in a tagline, lead, section or an episode summary, and every
  copy needs fixing (editorial patches can edit episode summaries and
  synopses too). Corrected fields are locked so re-processing a chapter can't
  silently undo them. If the manuscript itself still says the old thing, tell
  the author which file and line, but don't edit it. If the fix is really a
  mis-reading of an episode, correct and re-apply that episode's patch
  instead. Details: "Editorial patches" in `references/patch-format.md`.
- **Restyle the site**: write `<wiki>/custom.css` (CSS variables such as
  `--accent`, `--serif`, `--bg` are defined in `assets/style.css`), or change
  `accent` in `wiki.config.json`, then `build`.
- **Rebuild only**: `build`, then `log`.

## Ground rules

- Canon only: everything in the wiki must be supported by the text. Don't fill
  gaps with guesses. Open questions become threads.
- Don't edit the author's manuscript files; the wiki only reads them.
- Keep leads and taglines spoiler-light (who someone is), and put twists in the
  episode's history entry. The site's spoiler filter hides per-episode content
  beyond the reader's chosen episode.

## Troubleshooting

- `no wiki found`: wrong `--wiki` path; the folder must contain `wiki.config.json`.
- `scan` matches no files: fix `episode_globs` in `wiki.config.json`; globs are
  relative to `project_root` (default: the wiki folder's parent). `**` is supported.
- `entity id must be lowercase kebab-case`: use ids like `kael-varn`, `house-of-iron`.
- Patch JSON errors: nothing is saved on error, so fix the file and re-run.
- Episodes processed out of order are fine; pages and the guide always sort by
  episode number.
