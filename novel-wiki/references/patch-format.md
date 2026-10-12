# Episode patch format

One patch per episode: a JSON file holding everything that episode adds to the
wiki. `wiki.py apply` merges it into `data/wiki.json`, archives it to
`data/patches/ep-NNNN.json`, rebuilds the site and records a history run.

## Contents
1. Full example
2. `episode` object
3. `entities` and how each field merges
4. `timeline`, `glossary`, `threads`
5. Link syntax and formatting
6. Run log (`--run-log`)
7. Revisions and re-applying

## 1. Full example

(An invented space-opera story, used only to show the format.)

```json
{
  "episode": {
    "number": 7,
    "title": "Dead Reckoning",
    "arc": "Part Two: The Drift",
    "source": "episodes/07-dead-reckoning.md",
    "pov": ["juno-adeyemi"],
    "summary": "[[juno-adeyemi]] takes the [[lantern-key]] off the derelict [[saint-alder]] while [[the-quiet-fleet]] closes in.",
    "synopsis": [
      "The [[meridian]] docks with the derelict ...",
      "Inside the reactor hall ...",
      "The episode ends with ..."
    ],
    "word_count": 4210
  },
  "entities": [
    {
      "id": "juno-adeyemi",
      "type": "character",
      "name": "Juno Adeyemi",
      "aliases": ["Salvage Six"],
      "importance": "major",
      "tagline": "Salvage pilot of the Meridian.",
      "lead": "**Juno Adeyemi** is a salvage pilot from [[kesh-station]] and the main protagonist of the story.",
      "status": "Alive",
      "infobox": {"Age": "34", "Occupation": "Salvage pilot", "Affiliation": "[[meridian]] crew", "Family": ["[[obi-adeyemi]] (brother, missing)"]},
      "sections": {
        "Appearance": "Tall, shaved head, a prosthetic left hand of salvaged alloy.",
        "Personality": "Patient, sardonic, unwilling to leave anyone behind."
      },
      "history": "Juno cuts her way into the reactor hall of the [[saint-alder]] and takes the [[lantern-key]], but loses her tether line doing it.",
      "relationships": [{"target": "rook", "label": "Ship's AI and confidant", "note": "Argues with her about risk."}],
      "quotes": [{"text": "Dead ships don't lie. They just wait.", "context": "to Rook"}],
      "trivia": ["She names every tool she owns."],
      "presence": "pov"
    },
    {
      "id": "the-quiet-fleet",
      "type": "faction",
      "name": "The Quiet Fleet",
      "tagline": "Raiders who run without transponders.",
      "presence": "appears"
    },
    {
      "id": "obi-adeyemi",
      "type": "character",
      "name": "Obi Adeyemi",
      "tagline": "Juno's older brother.",
      "status": "Missing",
      "presence": "mentioned"
    }
  ],
  "timeline": [
    {"when": "Cycle 88, day 14", "sort": 88.014, "text": "The [[saint-alder]] is boarded for the first time in forty years.", "entities": ["juno-adeyemi"]}
  ],
  "glossary": [
    {"term": "Cold dock", "definition": "Docking with an unpowered ship by matching its spin by hand.", "see": "meridian"}
  ],
  "threads": [
    {"id": "who-crewed-the-alder", "title": "What happened to the Saint Alder's crew?", "text": "The crew's suits are all still in their lockers."},
    {"id": "rooks-gap", "title": "Rook's missing logs", "status": "resolved", "text": "Rook admits it deleted them.", "resolution": "Rook erased the logs to hide Obi's last message."}
  ]
}
```

## 2. `episode` (required)

| field | notes |
|---|---|
| `number` | Required. Number or numeric string (`3`, `"12.5"` for an interlude). Its key in the wiki. |
| `title` | The episode's own title, or the first heading. Falls back to "Episode N". |
| `arc` | Optional book, part, arc or season name. The episode guide groups by it. |
| `source` | Path of the episode file **relative to the project root**, exactly as `scan` printed it. Required so later scans can spot revisions. |
| `pov` | List of entity ids for viewpoint characters. They are auto-marked `pov` in appearances. |
| `summary` | 1–3 sentence recap: who, what changed, what's at stake. Shown in tables and search. |
| `synopsis` | List of paragraphs (or one string with blank lines). Full plot recap, past tense, in order, 3–10 paragraphs depending on episode length. |
| `word_count`, `notes` | Optional. |

## 3. `entities`

Every entity that **appears in or is mentioned by** this episode and has, or
deserves, a page. Include existing entities whenever this episode adds anything
about them. Upsert by `id`.

| field | merge rule |
|---|---|
| `id` | Required. Lowercase kebab-case, stable forever. Reuse ids from `brief`. One namespace across all types. `ep-` prefix is reserved. |
| `type` | Required when new. `character`, `location`, `faction`, `species`, `item`, `concept`, `event`. Other strings are allowed and get their own category (e.g. `ship`, `spell`, `planet`) but prefer the standard seven. |
| `name` | Required when new. Fullest canonical name revealed so far. Overwrites. |
| `aliases` | Added to the list (union). Nicknames, titles, false names, earlier names. |
| `importance` | `major` / `supporting` / `minor`. Overwrites. Controls grouping and the home page. |
| `tagline` | One line, overwrites. Card text and search snippet. |
| `lead` | Opening paragraph of the article, overwrites. Rewrite it to stay accurate as the story evolves. |
| `status` | Alive / Deceased / Missing / Destroyed / Unknown, etc. Overwrites. |
| `image` | Path to an image relative to the project root, if the author keeps art. |
| `infobox` | Key/value merge. Values are strings or lists of strings, and can contain links. `null` or `""` deletes a key. |
| `sections` | Key/value merge; each value **replaces** that section entirely, so send the full rewritten section, not just the new sentence. `null` deletes. Order of first insertion is kept. |
| `history` | String. Appended as this episode's entry in the "History" section. Only what happened in **this** episode. |
| `relationships` | List of `{target, label, note}`. Upserted by `target`. |
| `quotes` | List of strings or `{text, context}`. Appended. Verbatim from the text only. |
| `trivia` | List of strings. Appended (deduplicated). |
| `presence` | `appears` (default), `pov`, `mentioned`, or `none` (data update with no presence, e.g. a revelation about an absent character). |

## 4. Other blocks

**`timeline`**: `{when, sort, text, entities}`. `when` is the in-world date or
relative marker as the story states it ("Day 3", "Ten years before the Fall").
`sort` is an optional number for chronological ordering when it differs from
telling order (flashbacks): pick a scale and keep it consistent. Use it for
things that happen, not for descriptions.

**`glossary`**: `{term, definition, see}`. Upserted by term. For in-world
vocabulary, titles, slang and units that a reader may not know. `see` is an
optional entity id.

**`threads`**: `{id, title, text, status, resolution}`. Mysteries, promises,
prophecies, Chekhov's guns, unanswered questions. `text` is what this episode
adds to the thread. `status: "resolved"` plus `resolution` closes it. Reuse
open thread ids from `brief`.

## 5. Links and formatting (all free-text fields)

- `[[entity-id]]` links and shows the entity's name; `[[entity-id|shown text]]` for custom text.
- `[[ep:12]]` links to an episode page; `[[glossary:Cold dock]]` to a glossary entry.
- Before a name is revealed, link with display text: `[[obi-adeyemi|the pale pilot]]`.
  A bare `[[obi-adeyemi]]` always shows the page's *current* name.
- A link to an id that doesn't exist yet renders as a red "no page yet" link, and `apply` warns. Create the page or fix the id.
- `**bold**`, `*italic*`, blank line = new paragraph, lines starting `- ` form a list, a line starting `### ` is a sub-heading.
- No raw HTML; it's escaped.

## 6. Run log (`--run-log run.json`)

What the history page and `WIKI-HISTORY.md` show for this run. The engine adds
timestamp, episodes, created/updated/removed pages and warnings itself.

```json
{
  "request": "update wiki",
  "mode": "incremental update",
  "looked_at": ["wiki/wiki.config.json", "episodes/07-dead-reckoning.md", "wiki brief (42 entities)", "show: juno-adeyemi, rook"],
  "steps": [
    "Ran scan: 1 new file (episodes/07-dead-reckoning.md)",
    "Loaded wiki brief to reuse existing ids",
    "Read episode 7 in full (4,210 words)",
    "Pulled current records for juno-adeyemi and rook before rewriting their sections",
    "Wrote patch: 9 entities, 2 timeline events, 1 glossary term, 2 threads; dry run clean"
  ],
  "decisions": ["'The pale pilot' from episode 5 is named Obi in this episode: kept id obi-adeyemi, added the epithet as an alias"],
  "warnings": [],
  "notes": ""
}
```

## 7. Revisions

Re-applying a patch for an episode number that already exists first **rolls
back** everything that episode contributed (history entries, quotes, trivia,
relationships, appearances, timeline events, thread events) and then applies
the new patch. Pages, threads and glossary terms first created by that
episode that the new patch no longer mentions are removed. Things created by
*earlier* episodes are never removed by a rollback, so it is safe for a later
episode to update an earlier glossary term or thread.

The old archived patch isn't needed for rollback (the engine tags every
contribution with its episode), so just overwrite `data/patches/ep-NNNN.json`
with the new patch. Sections and leads are not rolled back (they are cumulative), so when
a revision changes a fact, rewrite the affected sections in the new patch.

To remove an episode the author deleted: `wiki.py forget --episode N`.

## 8. Editorial patches

For corrections and housekeeping that no single episode owns. Mark the patch
`"editorial": true` and omit `episode`. Only existing pages can be changed.

```json
{
  "editorial": true,
  "entities": [
    {"id": "juno-adeyemi", "infobox": {"Age": "35"}, "importance": "major"},
    {"id": "rook", "remove_aliases": ["R"], "relationships": [{"target": "obi-adeyemi", "delete": true}]},
    {"id": "the-pale-pilot", "delete": true}
  ],
  "glossary": [{"term": "Cold dock", "definition": "Corrected definition."}],
  "threads": [{"id": "who-crewed-the-alder", "title": "Where did the Saint Alder's crew go?"}],
  "episodes": {"7": {"title": "Dead Reckoning", "arc": "Part Two: The Drift"}}
}
```

Allowed per entity: everything in section 3 except `history`, `quotes` and
`presence` (those belong to an episode), plus `remove_aliases`, relationship
`delete`, and `"delete": true` to remove the page entirely. `episodes` can
change an episode's `title`, `arc`, `summary`, `synopsis`, `notes` and `pov`.

**Corrections are sticky.** Every scalar field (`name`, `tagline`, `lead`,
`status`, `importance`...) and every `infobox`/`sections` key set in an
editorial patch is locked: if a later episode patch (including re-processing a
revised chapter) sets a different value, the engine keeps the author's value
and prints a warning. To release a lock, send `"unlock": ["infobox.Age",
"tagline"]` on that entity in an editorial patch, typically together with the
new value or when the author confirms the manuscript now agrees.

Save editorial patches as `<wiki>/data/patches/editorial-YYYYMMDD-HHMM.json`. To merge a
duplicate, first move its content into the surviving page (aliases, sections,
infobox), then delete the duplicate in the same patch; per-episode history on
the deleted page is lost, so if it matters, re-apply the affected episodes'
patches with the surviving id instead.
