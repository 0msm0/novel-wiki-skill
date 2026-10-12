# Fan-wiki style guide

How the big fandom wikis (Wookieepedia, Tolkien Gateway, Narutopedia,
Memory Alpha, the Harry Potter Wiki) write, adapted for a novel still being
written. Read this on the first run and whenever unsure what deserves a page or
how to phrase it.

## Contents
1. Voice and canon rules
2. What gets a page
3. Article templates by type
4. Writing the episode guide
5. Keeping articles current

## 1. Voice and canon rules

- **In-universe, encyclopedic voice.** Write about characters as if they were
  real people in their world: "Juno was born on Kesh Station", not "the author
  introduces Juno". Neutral, never gushing. Out-of-universe notes ("Juno is the
  point-of-view character of Part One") belong in **Trivia** or **Behind the
  scenes** only.
- **Tense.** Descriptions of what something *is* in present tense (Appearance,
  Personality, Abilities, location descriptions). Events in **past tense**
  (History, synopses, timeline).
- **Canon only.** Everything must be supported by the episode text. No
  invention, no fan theories, no guessing at hidden motives. If the text
  only hints, say what it shows: "Rook appeared to recognise the signal."
  Open questions go to **threads**, not into articles as facts.
- **The text as written wins.** If a later episode contradicts an earlier one,
  record the latest canon in sections and note the change in Trivia
  ("In Episode 2 her eyes were described as grey; from Episode 9 they are
  green."). Mention it in the run log's `decisions` so the author sees a
  possible continuity slip.
- **When episodes disagree about the present state** (a revised early
  episode frees a character whom a later episode still treats as captured),
  set status and sections from the **latest episode in reading order** that
  speaks to it, add a Trivia note naming both episodes, and put the clash in the
  run log's `warnings`. The author decides which one changes; the wiki's job is
  to make the clash visible, not to resolve it.
- **Unreliable narrators and lies.** Record what a character *claims* as a
  claim ("Obi told the customs officer he was from Vey") and update when the truth is
  revealed.
- **Names reveal over time.** If someone is "the pale pilot" for several
  episodes and later named "Obi", there are two cases. *Processing episodes
  one at a time, before the reveal:* create the page under the epithet
  (`the-pale-pilot`, name "The pale pilot"); when the name arrives, rename it
  via `name` (keep the id) and add the epithet as an alias. *Already knowing the
  name (backlog run reading ahead):* use the real-name id from the start, but in
  pre-reveal episodes link it with the epithet as display text,
  `[[obi-adeyemi|the pale pilot]]`, and keep the name out of those episodes'
  history and synopsis text so the spoiler filter still works. When two pages turn out to be the
  same person, merge in one patch: move content into the surviving id, set the
  other to `presence: "none"` and note it in `decisions` (then tell the
  author; it can be deleted with a manual edit if needed).
- **Spoilers.** The site has a reader-controlled spoiler filter that works on
  per-episode entries (history, quotes, appearances, timeline, threads) and on
  pages' first appearance. Leads, taglines and sections are not filtered, so
  keep **leads and taglines** about who someone *is*, not twists ("Obi is
  Juno's older brother", not "Obi, the traitor who sold the station").
  Put twists in that episode's `history` entry.

## 2. What gets a page

Give a page when the thing is **named** and does at least one of:
- speaks, acts, or is acted upon in a way that matters to the plot;
- is a place where a scene happens, or is described in some detail;
- is a group, object, power, custom or word the reader must understand to
  follow the story;
- is mentioned more than once, or is clearly being set up.

Skip: unnamed walk-ons ("a guard"), throwaway brand names, generic objects.
A recurring unnamed figure ("the Grey Man") can have a page under that epithet.

Importance: **major** = protagonists, antagonists and the central cast;
**supporting** = recurring, matters to an arc; **minor** = everyone else with a
page. Revisit as the story grows; promotions are normal.

Type choice: a ship is an `item` unless the story treats ships as characters or
places; a planet, city, room or realm is a `location`; a war or battle is an
`event`; a magic system, technology, religion, language or custom is a
`concept`; an animal species or race is `species`. Genre-specific types
(`spell`, `ship`, `planet`) are allowed when a story has many of them.

## 3. Article templates

Use these section names (in this order) when there is material; skip empty ones.
Infobox keys are suggestions: use what the story establishes, never fill with
"Unknown" just to complete a row.

**Character**
- Infobox: Born / Age, Species, Gender, Height, Hair / Eyes, Occupation,
  Affiliation, Rank / Title, Family, Home, Abilities (short), Weapon
- Sections: Appearance, Personality, Abilities (powers, skills, combat style,
  equipment), Background (pre-story past as revealed), plus engine-managed
  History (per episode), Relationships, Quotes, Appearances, Trivia

**Location**
- Infobox: Type (city, ship, planet, forest...), Region / Located in, Ruler /
  Controlled by, Population, Notable residents, Climate
- Sections: Description, Geography, Culture / Society, Notable places,
  Background (in-world history)

**Faction / organisation**
- Infobox: Type, Leader, Headquarters, Founded, Members (notable), Allies,
  Enemies, Symbol / colours
- Sections: Overview, Structure & ranks, Beliefs & goals, Known members,
  Background

**Species**: Infobox: Homeworld / Range, Lifespan, Traits. Sections:
Biology, Culture, Known individuals.

**Item / artifact**: Infobox: Type, Creator, Owner(s) (in order), Material,
Powers. Sections: Description, Powers & properties, Background.

**Concept** (magic system, power, technology, religion, language): Infobox:
Type, Practitioners, Source / Origin. Sections: Overview, Rules & limitations
(very valuable for magic systems: list every rule the text establishes),
Known uses, Known users.

**Event**: Infobox: Date, Location, Participants, Result / Outcome,
Casualties. Sections: Background, Course of events, Aftermath.

Lead paragraph (all types): one to three sentences; bold the name on first use;
say what it is and why it matters, e.g. "**The Lantern Key** is a
data core recovered from the derelict Saint Alder. Its recovery puts the
Meridian's crew on the Quiet Fleet's hunting list."
Use the name exactly as the text writes it (keep "the" lowercase unless the
story capitalises it), and when the story never names a thing, title it by
its plainest description ("Brass compass").

## 4. Episode guide

- `summary`: 1–3 sentences naming the main characters, the central event, and
  what changes. No cliffhanger hiding: the wiki is a record.
- `synopsis`: several paragraphs, past tense, scene by scene, every important
  beat, decision and reveal. Link each entity on first mention per paragraph,
  not every mention.
- Title: the episode's own title, or a fitting one taken from its first
  heading; never invent a cute title if the author gave none, use
  "Episode N" instead (the engine does this when `title` is omitted).

## 5. Keeping articles current

For any existing entity this episode changes, first `show` its record, then
send **rewritten** `sections`, `lead`, `tagline` and `infobox` values that
integrate the new information with what's already there. A section is a
summary of everything known, not a changelog; the per-episode `history` entry
is the changelog. A character's Personality section after episode 20 should
read as a coherent portrait, not twenty appended sentences.
