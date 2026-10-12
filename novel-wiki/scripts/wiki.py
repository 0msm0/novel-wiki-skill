#!/usr/bin/env python3
"""novel-wiki engine.

Keeps the canonical wiki database for an ongoing novel and renders it as a
static HTML fan wiki. Claude does the reading and writes one JSON "patch" per
episode; this script does everything deterministic: merging, revision
rollback, cross-links, backlinks, the HTML site and the usage history.

Standard library only (Python 3.8+).

Commands (all take --wiki <dir>, default ./wiki):
  init   --title T [--globs G ...] [--label Chapter]  create a new wiki
  scan                         list episode files: NEW / CHANGED / OK / MISSING
  brief  [--type T]            compact index of everything known (for id reuse)
  show   ID [ID ...]           full JSON record of entities / threads
  apply  --patch P [...] [--run-log R]   merge patches, rebuild site, log run
  forget --episode N [--run-log R]       remove an episode's contributions
  build                        re-render the HTML site only
  log    --run-log R           record a run that changed no data
  check                        broken links, orphans, possible duplicates
"""
import argparse
import datetime
import glob
import hashlib
import html
import json
import os
import re
import shutil
import sys

VERSION = "1.0.0"
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(SKILL_DIR, "assets")

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# type -> (singular, plural, blurb). Unknown types are allowed and get a
# title-cased category of their own.
TYPE_INFO = {
    "character": ("Character", "Characters", "The people and beings who drive the story."),
    "location": ("Location", "Locations", "Worlds, realms, cities, ships and landmarks."),
    "faction": ("Faction", "Factions & Organizations", "Houses, guilds, crews, nations, orders and cults."),
    "species": ("Species", "Species & Races", "Peoples, creatures and kinds of being."),
    "item": ("Item", "Items & Artifacts", "Weapons, relics, vehicles, documents and objects that matter."),
    "concept": ("Concept", "Lore & Concepts", "Magic systems, powers, technologies, customs, religions and languages."),
    "event": ("Event", "Events", "Battles, wars, ceremonies, disasters and turning points."),
}
TYPE_ORDER = list(TYPE_INFO)
IMPORTANCE_ORDER = {"major": 0, "supporting": 1, "minor": 2}
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


# ---------------------------------------------------------------- utilities

def die(msg, code=2):
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(code)


def now_iso():
    return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "item"


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def file_hash(path):
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n")).strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def type_names(t):
    if t in TYPE_INFO:
        return TYPE_INFO[t]
    title = t.replace("-", " ").title()
    return (title, title + "s" if not title.endswith("s") else title, "")


def ep_key(n):
    try:
        return float(n)
    except (TypeError, ValueError):
        return float("inf")


def ep_str(n):
    # Episode numbers are stored as strings so "12.5" interludes work too.
    f = ep_key(n)
    return str(int(f)) if f == int(f) else str(f)


# ------------------------------------------------------------------ paths

class Wiki:
    def __init__(self, wiki_dir):
        self.dir = os.path.abspath(wiki_dir)
        self.config_path = os.path.join(self.dir, "wiki.config.json")
        self.data_path = os.path.join(self.dir, "data", "wiki.json")
        self.history_path = os.path.join(self.dir, "data", "history.json")
        self.patch_dir = os.path.join(self.dir, "data", "patches")
        self.site_dir = os.path.join(self.dir, "site")
        self.config = None
        self.data = None
        self.history = None

    def load(self):
        self.config = read_json(self.config_path)
        if self.config is None:
            die("no wiki found at %s (missing wiki.config.json). Run `init` first, or pass --wiki." % self.dir)
        self.data = read_json(self.data_path, None) or empty_data()
        for k, v in empty_data().items():
            self.data.setdefault(k, v)
        self.history = read_json(self.history_path, []) or []
        return self

    @property
    def project_root(self):
        return os.path.normpath(os.path.join(self.dir, self.config.get("project_root", "..")))

    @property
    def label(self):
        return self.config.get("episode_label", "Episode")

    def save(self):
        if os.path.exists(self.data_path):
            shutil.copyfile(self.data_path, self.data_path + ".bak")
        self.data["updated_at"] = now_iso()
        write_json(self.data_path, self.data)
        write_json(self.history_path, self.history)


def empty_data():
    return {"schema": 1, "updated_at": None, "episodes": {}, "entities": {},
            "timeline": [], "glossary": {}, "threads": {}}


# ------------------------------------------------------------------ init

def cmd_init(args):
    w = Wiki(args.wiki)
    if os.path.exists(w.config_path) and not args.force:
        die("a wiki already exists at %s. Use --force to overwrite the config only." % w.dir)
    os.makedirs(w.dir, exist_ok=True)
    root = os.path.abspath(args.project_root) if args.project_root else os.path.dirname(w.dir)
    cfg = {
        "title": args.title,
        "tagline": args.tagline or "",
        "author": args.author or "",
        "project_root": os.path.relpath(root, w.dir).replace("\\", "/"),
        "episode_globs": args.globs or ["chapters/*.md"],
        "episode_label": args.label or "Episode",
        "accent": args.accent or "#8b5cf6",
        "spoiler_filter": True,
    }
    write_json(w.config_path, cfg)
    if not os.path.exists(w.data_path):
        write_json(w.data_path, empty_data())
    if not os.path.exists(w.history_path):
        write_json(w.history_path, [])
    os.makedirs(w.patch_dir, exist_ok=True)
    print("Initialized novel wiki at %s" % w.dir)
    print(json.dumps(cfg, indent=2, ensure_ascii=False))


# ------------------------------------------------------------------ scan

def episode_files(w):
    root = w.project_root
    found = []
    for pattern in w.config.get("episode_globs", []):
        for p in glob.glob(os.path.join(root, pattern), recursive=True):
            if os.path.isfile(p) and os.path.abspath(p).find(os.sep + "site" + os.sep) == -1 \
                    and not os.path.abspath(p).startswith(w.dir + os.sep):
                found.append(os.path.relpath(p, root).replace("\\", "/"))
    return sorted(set(found), key=natural_key)


def cmd_scan(args):
    w = Wiki(args.wiki).load()
    files = episode_files(w)
    by_source = {e.get("source"): (n, e) for n, e in w.data["episodes"].items() if e.get("source")}
    rows, pending = [], 0
    for i, rel in enumerate(files, 1):
        h = file_hash(os.path.join(w.project_root, rel))
        if rel in by_source:
            n, e = by_source[rel]
            status = "OK" if e.get("hash") == h else "CHANGED"
        else:
            n, status = None, "NEW"
        if status != "OK":
            pending += 1
        rows.append((status, n, i, rel, h))
    print("Wiki: %s   project root: %s" % (w.config.get("title"), w.project_root))
    print("Episode globs: %s" % ", ".join(w.config.get("episode_globs", [])))
    print("%-8s %-8s %-6s %-18s %s" % ("STATUS", "EPISODE", "ORDER", "HASH", "FILE"))
    for status, n, i, rel, h in rows:
        print("%-8s %-8s %-6s %-18s %s" % (status, n or "-", i, h, rel))
    listed = {r[3] for r in rows}
    for n, e in sorted(w.data["episodes"].items(), key=lambda kv: ep_key(kv[0])):
        if e.get("source") and e["source"] not in listed:
            print("%-8s %-8s %-6s %-18s %s" % ("MISSING", n, "-", e.get("hash", ""), e["source"]))
    if not files:
        print("\nNo episode files matched. Fix episode_globs in %s" % w.config_path)
    nums = sorted((ep_key(n) for n in w.data["episodes"]), key=float)
    print("\n%d file(s) need processing. %d episode(s) in wiki%s." % (
        pending, len(nums), (", latest %s" % ep_str(nums[-1])) if nums else ""))


# ------------------------------------------------------------------ brief/show

def cmd_brief(args):
    w = Wiki(args.wiki).load()
    d = w.data
    print("# %s - wiki brief (%d entities, %d episodes)" % (w.config.get("title"), len(d["entities"]), len(d["episodes"])))
    print("Reuse these ids. Format: id | name | aliases | importance | first-last %s | tagline" % w.label.lower())
    ents = sorted(d["entities"].values(), key=lambda e: (type_rank(e["type"]), IMPORTANCE_ORDER.get(e.get("importance"), 3), e["name"].lower()))
    cur = None
    for e in ents:
        if args.type and e["type"] != args.type:
            continue
        if e["type"] != cur:
            cur = e["type"]
            print("\n## %s" % type_names(cur)[1])
        apps = sorted(e.get("appearances", {}), key=ep_key)
        span = "%s-%s" % (apps[0], apps[-1]) if apps else "-"
        print("%s | %s | %s | %s | %s | %s" % (e["id"], e["name"], ", ".join(e.get("aliases", [])) or "-",
                                               e.get("importance", "-"), span, e.get("tagline", "")))
    if not args.type:
        if d["threads"]:
            print("\n## Threads (id | status | title)")
            for t in sorted(d["threads"].values(), key=lambda t: (t["status"] != "open", ep_key(t.get("introduced")))):
                print("%s | %s | %s" % (t["id"], t["status"], t["title"]))
        if d["glossary"]:
            print("\n## Glossary terms\n" + ", ".join(sorted(g["term"] for g in d["glossary"].values())))
        eps = sorted(d["episodes"].values(), key=lambda e: ep_key(e["number"]))[-3:]
        if eps:
            print("\n## Most recent %ss" % w.label.lower())
            for e in eps:
                print("%s %s: %s - %s" % (w.label, e["number"], e.get("title", ""), e.get("summary", "")))


def type_rank(t):
    return TYPE_ORDER.index(t) if t in TYPE_ORDER else len(TYPE_ORDER)


def cmd_show(args):
    w = Wiki(args.wiki).load()
    out = {}
    for i in args.ids:
        if i in w.data["entities"]:
            out[i] = w.data["entities"][i]
        elif i in w.data["threads"]:
            out[i] = w.data["threads"][i]
        elif i.startswith("ep:") and i[3:] in w.data["episodes"]:
            out[i] = w.data["episodes"][i[3:]]
        else:
            out[i] = None
    print(json.dumps(out, indent=2, ensure_ascii=False))


# ------------------------------------------------------------------ apply

class PatchError(Exception):
    pass


def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def rollback_episode(d, n):
    """Remove everything episode n contributed, so a revised episode can be re-applied."""
    for e in d["entities"].values():
        e["history"] = [h for h in e.get("history", []) if h.get("episode") != n]
        e["quotes"] = [q for q in e.get("quotes", []) if q.get("episode") != n]
        e["trivia"] = [t for t in e.get("trivia", []) if t.get("episode") != n]
        e["relationships"] = [r for r in e.get("relationships", []) if r.get("episode") != n]
        e.get("appearances", {}).pop(n, None)
    d["timeline"] = [t for t in d["timeline"] if t.get("episode") != n]
    for t in d["threads"].values():
        t["events"] = [x for x in t.get("events", []) if x.get("episode") != n]
        if t.get("resolved_in") == n:
            t["resolved_in"] = None
            t["status"] = "open"
    d["episodes"].pop(n, None)


def prune_after_rollback(d, n, touched_ids, touched_threads, touched_terms):
    removed = []
    for i, e in list(d["entities"].items()):
        if e.get("created_in") == n and i not in touched_ids and not e.get("appearances") and not e.get("history"):
            del d["entities"][i]
            removed.append(i)
    for i, t in list(d["threads"].items()):
        if t.get("introduced") == n and i not in touched_threads and not t.get("events"):
            del d["threads"][i]
    for k, g in list(d["glossary"].items()):
        if g.get("created_in") == n and k not in touched_terms:
            del d["glossary"][k]
    return removed


def apply_editorial(d, patch, stats):
    """Corrections not tied to an episode: fix facts, merge duplicates, delete pages."""
    for raw in as_list(patch.get("entities")):
        eid = raw.get("id", "")
        if eid not in d["entities"]:
            raise PatchError("editorial patch can only change existing entities; %r not found" % eid)
        if raw.get("delete"):
            del d["entities"][eid]
            stats["removed"].append(eid)
            continue
        for k in ("history", "quotes", "presence"):
            if raw.get(k):
                raise PatchError("%s: '%s' belongs in an episode patch, not an editorial one" % (eid, k))
        e = d["entities"][eid]
        locks = e.setdefault("locks", {})
        for k in as_list(raw.get("unlock")):
            locks.pop(k, None)
        for k in ("type", "name", "tagline", "lead", "importance", "status", "image"):
            if raw.get(k) not in (None, ""):
                e[k] = raw[k]
                locks[k] = raw[k]
        for field in ("infobox", "sections"):
            for k, v in (raw.get(field) or {}).items():
                locks["%s.%s" % (field, k)] = v
        for a in as_list(raw.get("aliases")):
            if a and a not in e["aliases"] and a != e["name"]:
                e["aliases"].append(a)
        for a in as_list(raw.get("remove_aliases")):
            if a in e["aliases"]:
                e["aliases"].remove(a)
        for field in ("infobox", "sections"):
            for k, v in (raw.get(field) or {}).items():
                if v is None or v == "":
                    e[field].pop(k, None)
                else:
                    e[field][k] = v
        for r in as_list(raw.get("relationships")):
            if isinstance(r, dict) and r.get("target"):
                e["relationships"] = [x for x in e["relationships"] if x["target"] != r["target"]]
                if not r.get("delete"):
                    e["relationships"].append({"target": r["target"], "label": r.get("label", ""),
                                               "note": r.get("note", ""), "episode": None})
        for t in as_list(raw.get("trivia")):
            if t and t not in [x["text"] for x in e["trivia"]]:
                e["trivia"].append({"text": t, "episode": None})
        if eid not in stats["updated"]:
            stats["updated"].append(eid)
    for raw in as_list(patch.get("glossary")):
        if raw.get("term"):
            k = slugify(raw["term"])
            if raw.get("delete"):
                d["glossary"].pop(k, None)
            else:
                g = d["glossary"].setdefault(k, {"term": raw["term"], "created_in": None})
                g.update({k2: raw[k2] for k2 in ("term", "definition", "see") if k2 in raw})
    for raw in as_list(patch.get("threads")):
        t = d["threads"].get(raw.get("id"))
        if t is None:
            raise PatchError("editorial patch: thread %r not found" % raw.get("id"))
        if raw.get("delete"):
            del d["threads"][t["id"]]
            continue
        for k in ("title", "resolution"):
            if raw.get(k):
                t[k] = raw[k]
        if raw.get("status") in ("open", "resolved"):
            t["status"] = raw["status"]
    for n, fields in (patch.get("episodes") or {}).items():
        n = ep_str(n)
        if n not in d["episodes"]:
            raise PatchError("editorial patch: episode %s not found" % n)
        for k in ("title", "arc", "summary", "synopsis", "notes", "pov"):
            if k in fields:
                d["episodes"][n][k] = fields[k]
        merge_unique(stats["updated"], ["ep:" + n])


def apply_patch(d, patch, label, stats):
    if patch.get("editorial"):
        return apply_editorial(d, patch, stats)
    ep = patch.get("episode")
    if not isinstance(ep, dict) or "number" not in ep:
        raise PatchError("patch needs an 'episode' object with a 'number' (or \"editorial\": true for corrections)")
    n = ep_str(ep["number"])
    if ep_key(n) == float("inf"):
        raise PatchError("episode.number must be numeric, got %r" % ep["number"])
    revising = n in d["episodes"]
    old_episode = d["episodes"].get(n, {})
    if revising:
        rollback_episode(d, n)
        stats["revised"].append(n)

    synopsis = ep.get("synopsis", [])
    if isinstance(synopsis, str):
        synopsis = [p.strip() for p in re.split(r"\n\s*\n", synopsis) if p.strip()]
    d["episodes"][n] = {
        "number": n,
        "title": ep.get("title") or "%s %s" % (label, n),
        "arc": ep.get("arc") or old_episode.get("arc") or "",
        "source": ep.get("source") or old_episode.get("source") or "",
        "hash": ep.get("hash") or "",
        "pov": as_list(ep.get("pov")),
        "summary": ep.get("summary", ""),
        "synopsis": synopsis,
        "notes": ep.get("notes", ""),
        "word_count": ep.get("word_count"),
        "applied_at": now_iso(),
    }
    stats["episodes"].append(n)

    touched_ids, touched_threads, touched_terms = set(), set(), set()
    for raw in as_list(patch.get("entities")):
        eid = raw.get("id", "")
        if not ID_RE.match(eid):
            raise PatchError("entity id %r must be lowercase kebab-case (e.g. 'kael-varn')" % eid)
        if eid.startswith("ep-"):
            raise PatchError("entity id %r: the 'ep-' prefix is reserved" % eid)
        touched_ids.add(eid)
        e = d["entities"].get(eid)
        if e is None:
            if not raw.get("type") or not raw.get("name"):
                raise PatchError("new entity %r needs 'type' and 'name'" % eid)
            e = {"id": eid, "type": raw["type"], "name": raw["name"], "aliases": [], "tagline": "",
                 "lead": "", "importance": "minor", "status": "", "image": "", "infobox": {},
                 "sections": {}, "history": [], "relationships": [], "quotes": [], "trivia": [],
                 "appearances": {}, "created_in": n, "updated_in": n}
            d["entities"][eid] = e
            if eid not in stats["created"]:
                stats["created"].append(eid)
        elif eid not in stats["created"] and eid not in stats["updated"]:
            stats["updated"].append(eid)
        for k in ("type", "name", "tagline", "lead", "importance", "status", "image"):
            if raw.get(k) not in (None, ""):
                e[k] = raw[k]
        for a in as_list(raw.get("aliases")):
            if a and a not in e["aliases"] and a != e["name"]:
                e["aliases"].append(a)
        for k, v in (raw.get("infobox") or {}).items():
            if v is None or v == "":
                e["infobox"].pop(k, None)
            else:
                e["infobox"][k] = v
        for k, v in (raw.get("sections") or {}).items():
            if v is None or v == "":
                e["sections"].pop(k, None)
            else:
                e["sections"][k] = v
        if raw.get("history"):
            e["history"].append({"episode": n, "text": raw["history"]})
        for r in as_list(raw.get("relationships")):
            if isinstance(r, dict) and r.get("target"):
                e["relationships"] = [x for x in e["relationships"] if x["target"] != r["target"]]
                e["relationships"].append({"target": r["target"], "label": r.get("label", ""),
                                           "note": r.get("note", ""), "episode": n})
        for q in as_list(raw.get("quotes")):
            q = {"text": q} if isinstance(q, str) else q
            if q.get("text"):
                e["quotes"].append({"text": q["text"], "context": q.get("context", ""), "episode": n})
        for t in as_list(raw.get("trivia")):
            if t and t not in [x["text"] for x in e["trivia"]]:
                e["trivia"].append({"text": t, "episode": n})
        for k, v in (e.get("locks") or {}).items():
            field, _, key = k.partition(".")
            cur = e[field].get(key) if key else e.get(field)
            if cur != v and not (v is None and cur is None):
                stats["warnings"].append("%s: kept the author's correction %s=%r; %s %s's patch had %r (remove with an editorial \"unlock\")"
                                         % (eid, k, v, label, n, cur))
                if key:
                    if v in (None, ""):
                        e[field].pop(key, None)
                    else:
                        e[field][key] = v
                else:
                    e[field] = v
        presence = raw.get("presence", "appears")
        if presence != "none":
            e["appearances"][n] = presence if presence in ("appears", "mentioned", "pov") else "appears"
        e["updated_in"] = n

    for raw in as_list(patch.get("timeline")):
        if not raw.get("text"):
            continue
        d["timeline"].append({"when": raw.get("when", ""), "sort": raw.get("sort"), "text": raw["text"],
                              "entities": as_list(raw.get("entities")), "episode": n})

    for raw in as_list(patch.get("glossary")):
        if not raw.get("term"):
            continue
        k = slugify(raw["term"])
        touched_terms.add(k)
        g = d["glossary"].setdefault(k, {"term": raw["term"], "created_in": n})
        g.update({"term": raw["term"], "definition": raw.get("definition", g.get("definition", "")),
                  "see": raw.get("see", g.get("see", ""))})

    for raw in as_list(patch.get("threads")):
        tid = raw.get("id", "")
        if not ID_RE.match(tid):
            raise PatchError("thread id %r must be kebab-case" % tid)
        touched_threads.add(tid)
        t = d["threads"].get(tid)
        if t is None:
            t = {"id": tid, "title": raw.get("title", tid), "status": "open", "introduced": n,
                 "resolved_in": None, "events": [], "resolution": ""}
            d["threads"][tid] = t
        if raw.get("title"):
            t["title"] = raw["title"]
        if raw.get("text"):
            t["events"].append({"episode": n, "text": raw["text"]})
        if raw.get("status") == "resolved":
            t["status"] = "resolved"
            t["resolved_in"] = t.get("resolved_in") or n
            if raw.get("resolution"):
                t["resolution"] = raw["resolution"]
        elif raw.get("status") == "open":
            t["status"], t["resolved_in"] = "open", None

    # POV characters always count as appearing.
    for pid in d["episodes"][n]["pov"]:
        if pid in d["entities"]:
            d["entities"][pid]["appearances"][n] = "pov"

    if revising:
        stats["removed"] += prune_after_rollback(d, n, touched_ids, touched_threads, touched_terms)


def load_run_log(path):
    if not path:
        return {}
    log = read_json(path)
    if not isinstance(log, dict):
        die("run log %s must be a JSON object" % path)
    return log


def merge_unique(dst, items):
    for i in items:
        if i not in dst:
            dst.append(i)


def record_run(w, log, stats, mode, continue_run=False):
    if continue_run and w.history:
        # Fold this apply into the previous history entry (one user request, several applies).
        e = w.history[-1]
        for k in ("episodes", "revised", "removed"):
            merge_unique(e.setdefault(k, []), stats.get(k, []))
        merge_unique(e.setdefault("created", []), stats.get("created", []))
        merge_unique(e.setdefault("updated", []), [i for i in stats.get("updated", []) if i not in e["created"]])
        for k in ("looked_at", "steps", "decisions", "warnings"):
            merge_unique(e.setdefault(k, []), as_list(log.get(k)))
        e["warnings"] = [m for m in e["warnings"] if m not in stats.get("stale_warnings", [])]
        merge_unique(e["warnings"], stats.get("warnings", []))
        for k in ("request", "mode", "notes"):
            if log.get(k):
                e[k] = log[k]
        e["timestamp"] = now_iso()
        return e
    entry = {
        "run": (w.history[-1]["run"] + 1) if w.history else 1,
        "timestamp": now_iso(),
        "mode": log.get("mode") or mode,
        "request": log.get("request", ""),
        "episodes": stats.get("episodes", []),
        "revised": stats.get("revised", []),
        "created": stats.get("created", []),
        "updated": stats.get("updated", []),
        "removed": stats.get("removed", []),
        "looked_at": as_list(log.get("looked_at")),
        "steps": as_list(log.get("steps")),
        "decisions": as_list(log.get("decisions")),
        "warnings": as_list(log.get("warnings")) + stats.get("warnings", []),
        "notes": log.get("notes", ""),
        "engine_version": VERSION,
    }
    w.history.append(entry)
    return entry


def cmd_apply(args):
    w = Wiki(args.wiki).load()
    stats = {"episodes": [], "revised": [], "created": [], "updated": [], "removed": [], "warnings": []}
    patches = []
    for p in args.patch:
        try:
            patches.append((p, read_json(p)))
        except json.JSONDecodeError as ex:
            die("%s is not valid JSON: %s" % (p, ex))
    for p, patch in patches:
        if not isinstance(patch, dict):
            die("%s: a patch must be a JSON object" % p)
        try:
            apply_patch(w.data, patch, w.label, stats)
        except PatchError as ex:
            die("%s: %s (nothing was saved)" % (p, ex))
        if patch.get("editorial"):
            continue
        # Fill in the source hash so `scan` can spot later revisions.
        n = ep_str(patch["episode"]["number"])
        e = w.data["episodes"][n]
        src = e.get("source")
        if src:
            full = os.path.join(w.project_root, src)
            if os.path.exists(full):
                e["hash"] = file_hash(full)
            else:
                stats["warnings"].append("source %s for %s %s not found under project root" % (src, w.label, n))
    stats["warnings"] += [m for m in link_problems(w.data)][:50]
    if args.dry_run:
        print("DRY RUN - nothing saved. Would touch %s %s; create %d, update %d, remove %d." % (
            w.label.lower() + "s", ", ".join(stats["episodes"]) or "-", len(stats["created"]),
            len(stats["updated"]), len(stats["removed"])))
        print("New pages: %s" % (", ".join(stats["created"]) or "-"))
        for m in stats["warnings"]:
            print("WARNING: " + m)
        if not stats["warnings"]:
            print("No warnings.")
        return
    # Archive every patch: an audit trail of exactly what was extracted per episode.
    os.makedirs(w.patch_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    for p, patch in patches:
        if patch.get("editorial"):
            dest = os.path.join(w.patch_dir, "editorial-%s.json" % stamp)
        else:
            n = ep_str(patch["episode"]["number"])
            dest = os.path.join(w.patch_dir, "ep-%s.json" % n.replace(".", "_").zfill(4))
        if os.path.abspath(p) != os.path.abspath(dest):
            shutil.copyfile(p, dest)
    mode = "edit" if all(pt.get("editorial") for _, pt in patches) else "update"
    if args.continue_run and w.history:
        # Warnings from earlier applies in this run may now be fixed; keep only current ones.
        stats["stale_warnings"] = [m for m in w.history[-1].get("warnings", []) if m.startswith(("ep-", "timeline", "glossary", "thread:")) or " links to missing page " in m]
    log = load_run_log(args.run_log)
    entry = record_run(w, log, stats, mode, args.continue_run)
    d = w.data
    pages = 7 + len({e["type"] for e in d["entities"].values()}) + len(d["entities"]) + len(d["episodes"])
    entry["steps"].append("[engine] merged %s; rebuilt site (%d pages); %d link warning(s)" % (
        ("%s %s" % (w.label.lower() + ("s" if len(stats["episodes"]) > 1 else ""), ", ".join(stats["episodes"])))
        if stats["episodes"] else "editorial patch", pages, len(stats["warnings"])))
    w.save()
    build_site(w)
    print("Applied %d patch(es)%s" % (len(patches), (": %ss %s" % (w.label.lower(), ", ".join(stats["episodes"])))
                                      if stats["episodes"] else " (editorial)"))
    print("Created %d: %s" % (len(stats["created"]), ", ".join(stats["created"]) or "-"))
    print("Updated %d: %s" % (len(stats["updated"]), ", ".join(stats["updated"]) or "-"))
    if stats["revised"]:
        print("Revised (rolled back and re-applied): %s" % ", ".join(stats["revised"]))
    if stats["removed"]:
        print("Removed (no longer in revised text): %s" % ", ".join(stats["removed"]))
    for m in entry["warnings"]:
        print("WARNING: " + m)
    print("History run #%d recorded. Site: %s" % (entry["run"], os.path.join(w.site_dir, "index.html")))


def cmd_forget(args):
    w = Wiki(args.wiki).load()
    n = ep_str(args.episode)
    if n not in w.data["episodes"]:
        die("%s %s is not in the wiki" % (w.label, n))
    rollback_episode(w.data, n)
    removed = prune_after_rollback(w.data, n, set(), set(), set())
    entry = record_run(w, load_run_log(args.run_log), {"episodes": [], "revised": [n], "removed": removed}, "forget")
    w.save()
    build_site(w)
    print("Forgot %s %s. Removed entities: %s. Run #%d." % (w.label, n, ", ".join(removed) or "-", entry["run"]))


def cmd_log(args):
    w = Wiki(args.wiki).load()
    entry = record_run(w, load_run_log(args.run_log), {}, "no-change")
    w.save()
    build_site(w)
    print("History run #%d recorded." % entry["run"])


def cmd_build(args):
    w = Wiki(args.wiki).load()
    build_site(w)
    print("Built %s" % os.path.join(w.site_dir, "index.html"))


# ------------------------------------------------------------------ check

def all_text_fields(d):
    """Yield (owner, text) for every free-text field that may contain [[links]]."""
    for e in d["entities"].values():
        o = e["id"]
        for k in ("tagline", "lead", "status"):
            yield o, e.get(k, "")
        for v in e.get("infobox", {}).values():
            yield o, v if isinstance(v, str) else " ".join(map(str, as_list(v)))
        for v in e.get("sections", {}).values():
            yield o, v
        for h in e.get("history", []):
            yield o, h["text"]
        for r in e.get("relationships", []):
            yield o, "[[%s]] %s" % (r["target"], r.get("note", ""))
        for q in e.get("quotes", []):
            yield o, q.get("context", "")
        for t in e.get("trivia", []):
            yield o, t["text"]
    for n, ep in d["episodes"].items():
        o = "ep-" + n
        yield o, ep.get("summary", "")
        for p in ep.get("synopsis", []):
            yield o, p
        for p in ep.get("pov", []):
            yield o, "[[%s]]" % p
    for t in d["timeline"]:
        yield "timeline", t["text"]
        for x in t.get("entities", []):
            yield "timeline", "[[%s]]" % x
    for g in d["glossary"].values():
        yield "glossary", g.get("definition", "")
    for t in d["threads"].values():
        for ev in t.get("events", []):
            yield "thread:" + t["id"], ev["text"]
        yield "thread:" + t["id"], t.get("resolution", "")


def link_target_ok(d, target):
    target = target.strip()
    if target.startswith("ep:"):
        return ep_str(target[3:]) in d["episodes"]
    if target.startswith("glossary:"):
        return slugify(target[9:]) in d["glossary"]
    return target in d["entities"] or target in d["threads"]


def link_problems(d):
    seen = set()
    for owner, text in all_text_fields(d):
        for m in LINK_RE.finditer(text or ""):
            t = m.group(1).strip()
            if not link_target_ok(d, t) and (owner, t) not in seen:
                seen.add((owner, t))
                yield "%s links to missing page [[%s]]" % (owner, t)


def cmd_check(args):
    w = Wiki(args.wiki).load()
    d = w.data
    problems = list(link_problems(d))
    names = {}
    for e in d["entities"].values():
        for nm in [e["name"]] + e.get("aliases", []):
            names.setdefault(nm.lower(), []).append(e["id"])
        if not e.get("lead") and not e.get("tagline"):
            problems.append("%s has no lead or tagline" % e["id"])
        if not e.get("appearances"):
            problems.append("%s has no appearances" % e["id"])
    for nm, ids in names.items():
        if len(set(ids)) > 1:
            problems.append("name/alias '%s' is shared by %s - possible duplicate" % (nm, ", ".join(sorted(set(ids)))))
    for p in problems:
        print("- " + p)
    print("%d issue(s) found." % len(problems))


# ------------------------------------------------------------------ rendering

class Renderer:
    def __init__(self, w):
        self.w = w
        self.d = w.data
        self.cfg = w.config
        self.label = w.label
        self.backlinks = {}
        self.compute_backlinks()

    # -- helpers
    def compute_backlinks(self):
        for owner, text in all_text_fields(self.d):
            for m in LINK_RE.finditer(text or ""):
                t = m.group(1).strip()
                if t != owner:
                    self.backlinks.setdefault(t, set()).add(owner)

    def url(self, R, target):
        target = target.strip()
        if target.startswith("ep:"):
            return "%sepisodes/ep-%s.html" % (R, ep_str(target[3:]))
        if target.startswith("ep-"):
            return "%sepisodes/%s.html" % (R, target)
        if target.startswith("glossary:"):
            return "%sglossary.html#%s" % (R, slugify(target[9:]))
        if target in self.d["threads"]:
            return "%sthreads.html#%s" % (R, target)
        return "%swiki/%s.html" % (R, target)

    def name_of(self, target):
        target = target.strip()
        if target.startswith("ep:") or target.startswith("ep-"):
            n = ep_str(target[3:])
            ep = self.d["episodes"].get(n)
            return "%s %s%s" % (self.label, n, (": " + ep["title"]) if ep and ep.get("title") else "")
        if target.startswith("thread:"):
            target = target[7:]
        if target.startswith("glossary:"):
            g = self.d["glossary"].get(slugify(target[9:]))
            return g["term"] if g else target[9:]
        if target in self.d["entities"]:
            return self.d["entities"][target]["name"]
        if target in self.d["threads"]:
            return self.d["threads"][target]["title"]
        return {"timeline": "Timeline", "glossary": "Glossary"}.get(target, target.replace("-", " ").title())

    def link(self, R, target, text=None):
        target = target.strip()
        if target.startswith("thread:"):
            target = target[7:]
        if target in ("timeline", "glossary"):
            return '<a href="%s%s.html">%s</a>' % (R, target, esc(text or self.name_of(target)))
        ok = link_target_ok(self.d, target) or (target.startswith("ep-") and ep_str(target[3:]) in self.d["episodes"])
        if not ok:
            return '<span class="redlink" title="No page yet">%s</span>' % esc(text or target.replace("-", " ").title())
        return '<a href="%s">%s</a>' % (esc(self.url(R, target)), esc(text or self.name_of(target)))

    def inline(self, text, R):
        # Swap links for placeholders so emphasis can wrap them: *[[ship-id]]* -> italic link.
        links = []

        def hold(m):
            links.append(self.link(R, m.group(1), m.group(2)))
            return "\x00%d\x00" % (len(links) - 1)
        s = self._emph(esc(LINK_RE.sub(hold, str(text or ""))))
        return re.sub(r"\x00(\d+)\x00", lambda m: links[int(m.group(1))], s)

    @staticmethod
    def _emph(s):
        s = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?![\*\w])", r"<em>\1</em>", s)
        return s

    def blocks(self, text, R):
        html_out = []
        for block in re.split(r"\n\s*\n", str(text or "").strip()):
            lines = [l for l in block.split("\n") if l.strip()]
            if not lines:
                continue
            if all(re.match(r"\s*[-*] ", l) for l in lines):
                html_out.append("<ul>%s</ul>" % "".join(
                    "<li>%s</li>" % self.inline(re.sub(r"^\s*[-*] ", "", l), R) for l in lines))
            elif len(lines) == 1 and re.match(r"#{2,4} ", lines[0]):
                html_out.append("<h4>%s</h4>" % self.inline(lines[0].lstrip("# "), R))
            else:
                html_out.append("<p>%s</p>" % self.inline(" ".join(l.strip() for l in lines), R))
        return "\n".join(html_out)

    def ep_badge(self, R, n, short=False):
        n = ep_str(n)
        txt = ("%s%s" % (self.label[:2] + ". " if short else self.label + " ", n))
        if n in self.d["episodes"]:
            return '<a class="ep-badge" href="%sepisodes/ep-%s.html">%s</a>' % (R, n, esc(txt))
        return '<span class="ep-badge">%s</span>' % esc(txt)

    def sorted_eps(self):
        return sorted(self.d["episodes"].values(), key=lambda e: ep_key(e["number"]))

    def first_ep(self, e):
        apps = sorted(e.get("appearances", {}), key=ep_key)
        return apps[0] if apps else e.get("created_in")

    def page(self, R, title, body, active="", desc=""):
        cfg = self.cfg
        eps = self.sorted_eps()
        opts = "".join('<option value="%s">%s %s</option>' % (esc(e["number"]), esc(self.label), esc(e["number"])) for e in eps)
        types_present = self.types_present()
        nav = [("index.html", "Home", "home"), ("episodes.html", self.label + "s", "episodes")]
        nav += [("category/%s.html" % t, type_names(t)[1].split(" & ")[0], "cat-" + t) for t in types_present[:4]]
        nav += [("timeline.html", "Timeline", "timeline"), ("all-pages.html", "All pages", "all")]
        navhtml = "".join('<a href="%s%s"%s>%s</a>' % (R, href, ' class="active"' if key == active else "", esc(lbl))
                          for href, lbl, key in nav)
        spoiler = ""
        if cfg.get("spoiler_filter", True) and eps:
            spoiler = ('<label class="spoiler-ctl" title="Hide anything after the %s you have read">'
                       '<span>Read up to</span><select id="readUpTo"><option value="">Everything</option>%s</select></label>'
                       % (self.label.lower(), opts))
        return """<!doctype html>
<html lang="%(lang)s">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s | %(site)s Wiki</title>
<meta name="description" content="%(desc)s">
<meta name="generator" content="novel-wiki %(ver)s">
<link rel="stylesheet" href="%(R)sassets/style.css">
%(custom)s<style>:root{--accent:%(accent)s}</style>
<script>try{var t=localStorage.getItem('nw-theme');if(t)document.documentElement.dataset.theme=t}catch(e){}</script>
</head>
<body data-root="%(R)s" data-label="%(label)s">
<header class="top">
  <div class="top-inner">
    <a class="brand" href="%(R)sindex.html"><span class="brand-mark">%(mark)s</span><span>%(site)s <em>Wiki</em></span></a>
    <div class="search"><input id="q" type="search" placeholder="Search the wiki" autocomplete="off" aria-label="Search"><div id="results" class="results" hidden></div></div>
    <div class="tools">%(spoiler)s<button id="themeBtn" class="icon-btn" title="Toggle light/dark" aria-label="Toggle theme">&#9680;</button></div>
  </div>
  <nav class="nav">%(nav)s</nav>
</header>
<main class="wrap">
%(body)s
</main>
<footer class="foot">
  <p>%(site)s Wiki &middot; fan-wiki style encyclopedia of the novel%(author)s &middot; built %(built)s from %(neps)d %(labell)ss &middot; <a href="%(R)shistory.html">Wiki history</a> &middot; generated by novel-wiki %(ver)s</p>
</footer>
<script src="%(R)sassets/search-index.js"></script>
<script src="%(R)sassets/app.js"></script>
</body>
</html>
""" % {
            "lang": esc(cfg.get("language", "en")), "title": esc(title), "site": esc(cfg.get("title", "Novel")),
            "desc": esc(desc or cfg.get("tagline", "")), "ver": VERSION, "R": R, "accent": esc(cfg.get("accent", "#8b5cf6")),
            "custom": ('<link rel="stylesheet" href="%sassets/custom.css">\n' % R) if os.path.exists(os.path.join(self.w.dir, "custom.css")) else "",
            "label": esc(self.label), "mark": esc((cfg.get("title", "N").strip() or "N")[0].upper()),
            "spoiler": spoiler, "nav": navhtml, "body": body,
            "author": (" by " + esc(cfg["author"])) if cfg.get("author") else "",
            "built": esc(datetime.datetime.now().strftime("%Y-%m-%d %H:%M")), "neps": len(eps), "labell": esc(self.label.lower()),
        }

    def types_present(self):
        ts = {e["type"] for e in self.d["entities"].values()}
        return sorted(ts, key=lambda t: (type_rank(t), t))

    def card(self, R, e):
        fe = self.first_ep(e)
        img = ('<img src="%s" alt="" loading="lazy">' % esc(self.img_url(R, e))) if e.get("image") else \
            '<span class="card-initial">%s</span>' % esc(e["name"][:1].upper())
        return ('<a class="card" href="%swiki/%s.html" data-ep="%s"><div class="card-img">%s</div>'
                '<div class="card-body"><strong>%s</strong><span>%s</span>%s</div></a>') % (
            R, e["id"], esc(fe or ""), img, esc(e["name"]), self.inline_plain(e.get("tagline", "")),
            ('<small>%s</small>' % esc(e["status"])) if e.get("status") else "")

    def inline_plain(self, text):
        return esc(LINK_RE.sub(lambda m: m.group(2) or self.name_of(m.group(1)), str(text or "")))

    def img_url(self, R, e):
        return "%sassets/img/%s" % (R, os.path.basename(e["image"]))

    # -- pages
    def render_home(self):
        R, cfg, d = "", self.cfg, self.d
        eps = self.sorted_eps()
        latest = eps[-1] if eps else None
        stats = [(len(eps), self.label + "s")] + [(sum(1 for e in d["entities"].values() if e["type"] == t), type_names(t)[1])
                                                  for t in self.types_present()]
        stats += [(len(d["timeline"]), "Timeline events"), (sum(1 for t in d["threads"].values() if t["status"] == "open"), "Open threads")]
        statshtml = "".join('<div class="stat"><b>%d</b><span>%s</span></div>' % s for s in stats if s[0])
        major = [e for e in d["entities"].values() if e["type"] == "character" and e.get("importance") == "major"]
        if not major:
            major = sorted((e for e in d["entities"].values() if e["type"] == "character"),
                           key=lambda e: -len(e.get("appearances", {})))[:8]
        major.sort(key=lambda e: (ep_key(self.first_ep(e)), e["name"]))
        tiles = "".join('<a class="tile" href="category/%s.html"><b>%s</b><span>%s</span><em>%d pages</em></a>' % (
            t, esc(type_names(t)[1]), esc(type_names(t)[2]), sum(1 for e in d["entities"].values() if e["type"] == t))
            for t in self.types_present())
        tiles += '<a class="tile" href="timeline.html"><b>Timeline</b><span>Everything that happens, in order.</span><em>%d events</em></a>' % len(d["timeline"])
        if d["threads"]:
            tiles += '<a class="tile" href="threads.html"><b>Mysteries & Open Threads</b><span>Unanswered questions, foreshadowing and payoffs.</span><em>%d threads</em></a>' % len(d["threads"])
        if d["glossary"]:
            tiles += '<a class="tile" href="glossary.html"><b>Glossary</b><span>Terms, titles and in-world words.</span><em>%d terms</em></a>' % len(d["glossary"])
        latest_html = ""
        if latest:
            latest_html = ('<section class="panel latest" data-ep="%s"><h2>Latest %s</h2><h3><a href="episodes/ep-%s.html">%s %s: %s</a></h3>%s</section>'
                           % (esc(latest["number"]), esc(self.label.lower()), esc(latest["number"]), esc(self.label), esc(latest["number"]),
                              esc(latest["title"]), self.blocks(latest.get("summary", ""), R)))
        extra = ""
        if latest:
            qs = [(e, q) for e in d["entities"].values() for q in e.get("quotes", []) if q.get("episode") == latest["number"]]
            if qs:
                e, q = max(qs, key=lambda eq: (eq[0].get("importance") == "major", len(eq[1]["text"])))
                extra += ('<section class="panel" data-ep="%s"><h2>Quote of the %s</h2><blockquote><p>&ldquo;%s&rdquo;</p>'
                          '<cite>&mdash; %s</cite></blockquote></section>') % (
                    esc(latest["number"]), esc(self.label.lower()), self.inline(q["text"], R), self.link(R, e["id"]))
        opent = sorted((t for t in d["threads"].values() if t["status"] == "open"), key=lambda t: -ep_key(t.get("introduced")))
        if opent:
            extra += '<section class="panel"><h2>Open mysteries</h2><ul class="recent">%s</ul><p><a href="threads.html">All %d threads &rarr;</a></p></section>' % (
                "".join('<li data-ep="%s"><a href="threads.html#%s">%s</a></li>' % (esc(t.get("introduced")), esc(t["id"]), esc(t["title"])) for t in opent[:6]),
                len(d["threads"]))
        recent = ""
        for h in reversed(self.w.history[-5:]):
            bits = []
            if h.get("episodes"):
                bits.append("added %s %s" % (self.label.lower() + ("s" if len(h["episodes"]) > 1 else ""), ", ".join(h["episodes"])))
            if h.get("created"):
                bits.append("%d new page%s" % (len(h["created"]), "s" if len(h["created"]) != 1 else ""))
            if h.get("updated"):
                bits.append("%d updated" % len(h["updated"]))
            recent += '<li><time>%s</time> %s</li>' % (esc(h["timestamp"][:16].replace("T", " ")), esc("; ".join(bits) or h.get("mode", "")))
        body = """
<section class="hero">
  <p class="kicker">The fan encyclopedia</p>
  <h1>%s</h1>
  %s
  <div class="stats">%s</div>
</section>
<div class="home-grid">
  <div>
    %s
    <section class="panel"><h2>Main characters</h2><div class="cards">%s</div></section>
    <section class="panel"><h2>Explore the wiki</h2><div class="tiles">%s</div></section>
  </div>
  <aside>
    %s
    <section class="panel"><h2>Recent changes</h2><ul class="recent">%s</ul><p><a href="history.html">Full wiki history &rarr;</a></p></section>
    <section class="panel"><h2>%ss</h2><ol class="eplist">%s</ol></section>
  </aside>
</div>""" % (esc(cfg.get("title")), ('<p class="tagline">%s</p>' % esc(cfg["tagline"])) if cfg.get("tagline") else "",
             statshtml, latest_html, "".join(self.card(R, e) for e in major) or "<p class='muted'>No characters yet.</p>",
             tiles, extra, recent or "<li class='muted'>No runs yet.</li>", esc(self.label),
             "".join('<li data-ep="%s"><a href="episodes/ep-%s.html"><span>%s</span> %s</a></li>' % (
                 esc(e["number"]), esc(e["number"]), esc(e["number"]), esc(e["title"])) for e in eps[-12:]))
        return self.page(R, "Home", body, "home")

    def render_category(self, t):
        R = "../"
        sing, plural, blurb = type_names(t)
        ents = [e for e in self.d["entities"].values() if e["type"] == t]
        groups = []
        for imp, title in (("major", "Main"), ("supporting", "Supporting"), ("minor", "Minor")):
            g = sorted((e for e in ents if (e.get("importance") or "minor") == imp), key=lambda e: (ep_key(self.first_ep(e)), e["name"]))
            if g:
                groups.append('<section class="panel"><h2>%s %s</h2><div class="cards">%s</div></section>' % (
                    title, esc(plural.lower()), "".join(self.card(R, e) for e in g)))
        other = [e for e in ents if (e.get("importance") or "minor") not in IMPORTANCE_ORDER]
        if other:
            groups.append('<section class="panel"><div class="cards">%s</div></section>' % "".join(self.card(R, e) for e in other))
        body = '<header class="page-head"><p class="kicker">Category</p><h1>%s</h1><p class="lead">%s</p></header>%s' % (
            esc(plural), esc(blurb), "".join(groups))
        return self.page(R, plural, body, "cat-" + t, blurb)

    def render_entity(self, e):
        R = "../"
        d = self.d
        sing = type_names(e["type"])[0]
        apps = sorted(e.get("appearances", {}).items(), key=lambda kv: ep_key(kv[0]))
        first = self.first_ep(e)
        # infobox
        rows = []
        for k, v in e.get("infobox", {}).items():
            vals = as_list(v)
            rows.append("<tr><th>%s</th><td>%s</td></tr>" % (esc(k), "<br>".join(self.inline(x, R) for x in vals)))
        if e.get("aliases"):
            rows.insert(0, "<tr><th>Also known as</th><td>%s</td></tr>" % "<br>".join(esc(a) for a in e["aliases"]))
        if e.get("status"):
            rows.append("<tr><th>Status</th><td>%s</td></tr>" % self.inline(e["status"], R))
        if apps:
            rows.append("<tr><th>First appearance</th><td>%s</td></tr>" % self.ep_badge(R, apps[0][0]))
            last_seen = [n for n, p in apps if p != "mentioned"]
            if last_seen and last_seen[-1] != apps[0][0]:
                rows.append("<tr><th>Latest appearance</th><td>%s</td></tr>" % self.ep_badge(R, last_seen[-1]))
            rows.append("<tr><th>%ss</th><td>%d</td></tr>" % (esc(self.label), len(apps)))
        img = ('<img class="infobox-img" src="%s" alt="%s">' % (esc(self.img_url(R, e)), esc(e["name"]))) if e.get("image") else ""
        infobox = ('<aside class="infobox"><div class="infobox-title">%s</div>%s<div class="infobox-type">%s</div>'
                   '<table>%s</table></aside>') % (esc(e["name"]), img, esc(sing), "".join(rows))
        # sections
        secs, toc = [], []

        def add(sid, title, content):
            if content:
                toc.append('<li><a href="#%s">%s</a></li>' % (sid, esc(title)))
                secs.append('<section id="%s"><h2>%s</h2>%s</section>' % (sid, esc(title), content))

        for k, v in e.get("sections", {}).items():
            add("s-" + slugify(k), k, self.blocks(v, R))
        if e.get("history"):
            hist = "".join('<div class="hist" data-ep="%s"><h3>%s %s</h3>%s</div>' % (
                esc(h["episode"]), self.ep_badge(R, h["episode"]),
                esc(d["episodes"].get(h["episode"], {}).get("title", "")), self.blocks(h["text"], R))
                for h in sorted(e["history"], key=lambda h: ep_key(h["episode"])))
            add("history", "History" if e["type"] != "location" else "History in the story", hist)
        if e.get("relationships"):
            rel = "".join('<tr data-ep="%s"><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                esc(r["episode"]), self.link(R, r["target"]), self.inline(r.get("label", ""), R), self.inline(r.get("note", ""), R))
                for r in e["relationships"])
            add("relationships", "Relationships", '<table class="tbl"><thead><tr><th>Who / what</th><th>Relation</th><th>Notes</th></tr></thead><tbody>%s</tbody></table>' % rel)
        if e.get("quotes"):
            add("quotes", "Quotes", "".join('<blockquote data-ep="%s"><p>&ldquo;%s&rdquo;</p><cite>%s%s</cite></blockquote>' % (
                esc(q["episode"]), self.inline(q["text"], R), (self.inline(q["context"], R) + " &middot; ") if q.get("context") else "",
                self.ep_badge(R, q["episode"])) for q in e["quotes"]))
        if apps:
            add("appearances", "Appearances", '<ul class="apps">%s</ul>' % "".join(
                '<li data-ep="%s">%s <span class="muted">%s</span></li>' % (
                    esc(n), self.ep_badge(R, n) + " " + esc(d["episodes"].get(n, {}).get("title", "")),
                    {"mentioned": "(mentioned)", "pov": "(point of view)"}.get(p, "")) for n, p in apps))
        if e.get("trivia"):
            add("trivia", "Trivia", "<ul>%s</ul>" % "".join('<li data-ep="%s">%s</li>' % (esc(t["episode"]), self.inline(t["text"], R)) for t in e["trivia"]))
        bl = sorted(self.backlinks.get(e["id"], set()) - {e["id"]}, key=lambda o: self.name_of(o).lower())
        if bl:
            add("links-here", "What links here", '<ul class="cols">%s</ul>' % "".join("<li>%s</li>" % self.link(R, o) for o in bl))
        tochtml = '<nav class="toc"><b>Contents</b><ol>%s</ol></nav>' % "".join(toc) if len(toc) > 2 else ""
        body = """<article class="article" data-ep="%s">
<header class="page-head"><p class="kicker"><a href="../category/%s.html">%s</a></p><h1>%s</h1>%s</header>
<div class="article-grid"><div class="article-main">%s%s%s</div>%s</div>
</article>""" % (esc(first or ""), esc(e["type"]), esc(type_names(e["type"])[1]), esc(e["name"]),
                 ('<p class="tagline">%s</p>' % self.inline(e["tagline"], R)) if e.get("tagline") else "",
                 self.blocks(e.get("lead", ""), R), tochtml, "".join(secs), infobox)
        return self.page(R, e["name"], body, "cat-" + e["type"], self.inline_plain(e.get("tagline", "")))

    def render_episodes_index(self):
        R = ""
        eps = self.sorted_eps()
        arcs, order = {}, []
        for e in eps:
            a = e.get("arc") or ""
            if a not in arcs:
                arcs[a] = []
                order.append(a)
            arcs[a].append(e)
        out = []
        for a in order:
            rows = "".join('<tr data-ep="%s"><td class="num">%s</td><td><a href="episodes/ep-%s.html">%s</a></td><td>%s</td><td>%s</td></tr>' % (
                esc(e["number"]), esc(e["number"]), esc(e["number"]), esc(e["title"]),
                ", ".join(self.link(R, p) for p in e.get("pov", [])) or "&mdash;", self.inline(e.get("summary", ""), R)) for e in arcs[a])
            out.append('<section class="panel">%s<table class="tbl eps"><thead><tr><th>#</th><th>Title</th><th>POV</th><th>Summary</th></tr></thead><tbody>%s</tbody></table></section>' % (
                ("<h2>%s</h2>" % esc(a)) if a else "", rows))
        body = '<header class="page-head"><p class="kicker">Guide</p><h1>%s guide</h1><p class="lead">Every %s so far, in reading order.</p></header>%s' % (
            esc(self.label), esc(self.label.lower()), "".join(out) or "<p class='muted'>Nothing yet.</p>")
        return self.page(R, self.label + " guide", body, "episodes")

    def render_episode(self, e, prev, nxt):
        R = "../"
        n = e["number"]
        d = self.d
        cast = [(x, x.get("appearances", {}).get(n)) for x in d["entities"].values() if n in x.get("appearances", {})]
        groups = {}
        for x, p in cast:
            groups.setdefault(x["type"], []).append((x, p))
        castsec = ""
        for t in sorted(groups, key=type_rank):
            items = sorted(groups[t], key=lambda xp: (xp[1] == "mentioned", IMPORTANCE_ORDER.get(xp[0].get("importance"), 3), xp[0]["name"]))
            castsec += "<h3>%s</h3><ul class='cols'>%s</ul>" % (esc(type_names(t)[1]), "".join(
                "<li>%s%s</li>" % (self.link(R, x["id"]), {"mentioned": " <span class='muted'>(mentioned)</span>", "pov": " <span class='muted'>(POV)</span>"}.get(p, ""))
                for x, p in items))
        tl = [t for t in d["timeline"] if t.get("episode") == n]
        threads = [(t, ev) for t in d["threads"].values() for ev in t.get("events", []) if ev["episode"] == n]
        newp = [x for x in d["entities"].values() if x.get("created_in") == n]
        meta = []
        if e.get("arc"):
            meta.append("<tr><th>Arc</th><td>%s</td></tr>" % esc(e["arc"]))
        if e.get("pov"):
            meta.append("<tr><th>Point of view</th><td>%s</td></tr>" % ", ".join(self.link(R, p) for p in e["pov"]))
        if e.get("word_count"):
            meta.append("<tr><th>Length</th><td>%s words</td></tr>" % esc(e["word_count"]))
        if prev:
            meta.append("<tr><th>Previous</th><td>%s</td></tr>" % self.link(R, "ep:" + prev["number"]))
        if nxt:
            meta.append("<tr><th>Next</th><td>%s</td></tr>" % self.link(R, "ep:" + nxt["number"]))
        if newp:
            meta.append("<tr><th>Debuts</th><td>%s</td></tr>" % "<br>".join(self.link(R, x["id"]) for x in sorted(newp, key=lambda x: (type_rank(x["type"]), x["name"]))))
        secs = []
        if e.get("synopsis"):
            secs.append('<section id="synopsis"><h2>Synopsis</h2>%s</section>' % "".join(self.blocks(p, R) for p in e["synopsis"]))
        if castsec:
            secs.append('<section id="featured"><h2>Featured</h2>%s</section>' % castsec)
        if tl:
            secs.append('<section><h2>Timeline events</h2><ul>%s</ul></section>' % "".join(
                "<li>%s%s</li>" % (("<b>%s</b> &mdash; " % esc(t["when"])) if t.get("when") else "", self.inline(t["text"], R)) for t in tl))
        if threads:
            secs.append('<section><h2>Threads</h2><ul>%s</ul></section>' % "".join(
                '<li><a href="../threads.html#%s">%s</a>: %s</li>' % (esc(t["id"]), esc(t["title"]), self.inline(ev["text"], R)) for t, ev in threads))
        if e.get("notes"):
            secs.append('<section><h2>Notes</h2>%s</section>' % self.blocks(e["notes"], R))
        pager = '<nav class="pager">%s%s</nav>' % (
            ('<a href="ep-%s.html">&larr; %s %s</a>' % (esc(prev["number"]), esc(self.label), esc(prev["number"]))) if prev else "<span></span>",
            ('<a href="ep-%s.html">%s %s &rarr;</a>' % (esc(nxt["number"]), esc(self.label), esc(nxt["number"]))) if nxt else "<span></span>")
        body = """<article class="article episode" data-ep="%s">
<header class="page-head"><p class="kicker"><a href="../episodes.html">%s %s</a></p><h1>%s</h1></header>
<div class="article-grid"><div class="article-main"><div class="lead">%s</div>%s%s</div>
<aside class="infobox"><div class="infobox-title">%s %s</div><table>%s</table></aside></div>
</article>""" % (esc(n), esc(self.label), esc(n), esc(e["title"]), self.blocks(e.get("summary", ""), R), "".join(secs), pager,
                 esc(self.label), esc(n), "".join(meta))
        return self.page(R, "%s %s: %s" % (self.label, n, e["title"]), body, "episodes", self.inline_plain(e.get("summary", "")))

    def render_timeline(self):
        R = ""
        order = {e["number"]: i for i, e in enumerate(self.sorted_eps())}
        items = sorted(enumerate(self.d["timeline"]), key=lambda it: (
            it[1]["sort"] if isinstance(it[1].get("sort"), (int, float)) else float("inf"),
            order.get(it[1]["episode"], 1e9), it[0]))
        lis = "".join('<li data-ep="%s"><div class="when">%s</div><div class="what">%s<div class="meta">%s%s</div></div></li>' % (
            esc(t["episode"]), esc(t.get("when") or ""), self.blocks(t["text"], R), self.ep_badge(R, t["episode"]),
            ("".join(" " + self.link(R, x) for x in t.get("entities", [])))) for _, t in items)
        body = ('<header class="page-head"><p class="kicker">Chronology</p><h1>Timeline</h1><p class="lead">Events in in-world order '
                '(where the story gives a date or sequence), otherwise in the order they are told.</p></header><ol class="timeline">%s</ol>') % (
            lis or "<li class='muted'>No events yet.</li>")
        return self.page(R, "Timeline", body, "timeline")

    def render_glossary(self):
        R = ""
        terms = sorted(self.d["glossary"].values(), key=lambda g: g["term"].lower())
        body = '<header class="page-head"><p class="kicker">Reference</p><h1>Glossary</h1></header><dl class="glossary">%s</dl>' % "".join(
            '<dt id="%s" data-ep="%s">%s</dt><dd data-ep="%s">%s%s</dd>' % (
                esc(slugify(g["term"])), esc(g.get("created_in", "")), esc(g["term"]), esc(g.get("created_in", "")),
                self.inline(g.get("definition", ""), R), (" <span class='muted'>See %s.</span>" % self.link(R, g["see"])) if g.get("see") else "")
            for g in terms)
        return self.page(R, "Glossary", body, "glossary")

    def render_threads(self):
        R = ""
        out = []
        for status, title in (("open", "Open threads & mysteries"), ("resolved", "Resolved")):
            ts = sorted((t for t in self.d["threads"].values() if t["status"] == status), key=lambda t: ep_key(t.get("introduced")))
            if not ts:
                continue
            cards = "".join('<div class="thread %s" id="%s" data-ep="%s"><h3>%s</h3><p class="muted">Introduced in %s%s</p><ul>%s</ul>%s</div>' % (
                status, esc(t["id"]), esc(t.get("introduced")), esc(t["title"]), self.ep_badge(R, t.get("introduced")),
                (" &middot; resolved in " + self.ep_badge(R, t["resolved_in"])) if t.get("resolved_in") else "",
                "".join('<li data-ep="%s">%s %s</li>' % (esc(ev["episode"]), self.ep_badge(R, ev["episode"], True), self.inline(ev["text"], R)) for ev in t.get("events", [])),
                ('<p class="resolution" data-ep="%s"><b>Resolution:</b> %s</p>' % (esc(t.get("resolved_in")), self.inline(t["resolution"], R))) if t.get("resolution") else "")
                for t in ts)
            out.append('<section class="panel"><h2>%s</h2>%s</section>' % (title, cards))
        body = ('<header class="page-head"><p class="kicker">Story threads</p><h1>Mysteries & Open Threads</h1>'
                '<p class="lead">Unanswered questions, promises and foreshadowing the story has set up, and where they paid off.</p></header>%s') % "".join(out)
        return self.page(R, "Mysteries & Open Threads", body, "threads")

    def render_all_pages(self):
        R = ""
        ents = sorted(self.d["entities"].values(), key=lambda e: e["name"].lower())
        groups = {}
        for e in ents:
            k = e["name"][:1].upper()
            groups.setdefault(k if k.isalpha() else "#", []).append(e)
        body = '<header class="page-head"><p class="kicker">Index</p><h1>All pages</h1><p class="lead">%d articles.</p></header>%s' % (
            len(ents), "".join('<section class="panel"><h2>%s</h2><ul class="cols">%s</ul></section>' % (
                esc(k), "".join('<li data-ep="%s">%s <span class="muted">%s</span></li>' % (
                    esc(self.first_ep(e) or ""), self.link(R, e["id"]), esc(type_names(e["type"])[0].lower())) for e in groups[k]))
                for k in sorted(groups)))
        return self.page(R, "All pages", body, "all")

    def render_history(self):
        R = ""
        cards = []
        for h in reversed(self.w.history):
            def lst(title, items, linker=None, tag="ul"):
                if not items:
                    return ""
                return "<h4>%s</h4><%s>%s</%s>" % (title, tag, "".join("<li>%s</li>" % (linker(i) if linker else self.inline(i, R)) for i in items), tag)
            epl = lambda n: self.link(R, "ep:" + n) if n in self.d["episodes"] else esc("%s %s" % (self.label, n))
            entl = lambda i: self.link(R, i) if (i in self.d["entities"] or i.startswith("ep:")) else "<s>%s</s>" % esc(i)
            cards.append("""<article class="run panel" id="run-%d">
<header><h2>Run #%d <span class="mode">%s</span></h2><time>%s</time></header>
%s
<div class="run-grid"><div>%s%s%s%s%s</div><div>%s%s%s%s</div></div>
%s
</article>""" % (h["run"], h["run"], esc(h.get("mode", "")), esc(h["timestamp"].replace("T", " ")),
                 ('<p class="req"><b>Request:</b> &ldquo;%s&rdquo;</p>' % esc(h["request"])) if h.get("request") else "",
                 lst("Steps performed", h.get("steps", []), tag="ol"),
                 lst(self.label + "s processed", h.get("episodes"), epl), lst("Revised / re-applied", h.get("revised"), epl),
                 lst("Decisions", h.get("decisions")), lst("Warnings", h.get("warnings")),
                 lst("Looked at", h.get("looked_at"), lambda s: "<code>%s</code>" % esc(s)),
                 lst("Pages created (%d)" % len(h.get("created", [])), h.get("created"), entl),
                 lst("Pages updated (%d)" % len(h.get("updated", [])), h.get("updated"), entl),
                 lst("Pages removed", h.get("removed"), lambda i: "<s>%s</s>" % esc(i)),
                 ('<p class="muted">%s</p>' % self.inline(h["notes"], R)) if h.get("notes") else ""))
        body = ('<header class="page-head"><p class="kicker">Maintenance log</p><h1>Wiki history</h1><p class="lead">Every time the wiki was built or updated: '
                'what was asked, which files were read, what steps ran and which pages changed.</p></header>%s') % (
            "".join(cards) or "<p class='muted'>No runs recorded yet.</p>")
        return self.page(R, "Wiki history", body, "history")

    def search_index(self):
        idx = []
        for e in self.d["entities"].values():
            idx.append({"t": e["name"], "u": "wiki/%s.html" % e["id"], "k": type_names(e["type"])[0],
                        "a": " ".join(e.get("aliases", [])), "s": self.inline_plain(e.get("tagline", ""))[:140],
                        "ep": self.first_ep(e) or ""})
        for e in self.sorted_eps():
            idx.append({"t": "%s %s: %s" % (self.label, e["number"], e["title"]), "u": "episodes/ep-%s.html" % e["number"],
                        "k": self.label, "a": "", "s": self.inline_plain(e.get("summary", ""))[:140], "ep": e["number"]})
        for g in self.d["glossary"].values():
            idx.append({"t": g["term"], "u": "glossary.html#%s" % slugify(g["term"]), "k": "Glossary", "a": "",
                        "s": self.inline_plain(g.get("definition", ""))[:140], "ep": g.get("created_in", "")})
        for t in self.d["threads"].values():
            idx.append({"t": t["title"], "u": "threads.html#%s" % t["id"], "k": "Thread", "a": "", "s": "", "ep": t.get("introduced", "")})
        return "window.WIKI_INDEX=" + json.dumps(idx, ensure_ascii=False) + ";\n"


def history_markdown(w):
    lines = ["# Wiki history - %s" % w.config.get("title", ""), "",
             "Generated by novel-wiki. One entry per run, newest first. The same log is published at `site/history.html`.", ""]
    for h in reversed(w.history):
        lines.append("## Run #%d - %s (%s)" % (h["run"], h["timestamp"].replace("T", " "), h.get("mode", "")))
        if h.get("request"):
            lines.append("**Request:** %s  " % h["request"])
        for k, title in (("episodes", w.label + "s processed"), ("revised", "Revised"), ("created", "Pages created"),
                         ("updated", "Pages updated"), ("removed", "Pages removed")):
            if h.get(k):
                lines.append("**%s:** %s  " % (title, ", ".join(h[k])))
        if h.get("steps"):
            lines += ["", "**Steps:**"] + ["%d. %s" % (i + 1, s) for i, s in enumerate(h["steps"])]
        if h.get("looked_at"):
            lines += ["", "**Looked at:**"] + ["- `%s`" % s for s in h["looked_at"]]
        for k, title in (("decisions", "Decisions"), ("warnings", "Warnings")):
            if h.get(k):
                lines += ["", "**%s:**" % title] + ["- %s" % s for s in h[k]]
        if h.get("notes"):
            lines += ["", h["notes"]]
        lines.append("")
    return "\n".join(lines)


def build_site(w):
    r = Renderer(w)
    site = w.site_dir
    # Wipe generated page folders so renamed/removed pages do not linger.
    for sub in ("wiki", "episodes", "category"):
        shutil.rmtree(os.path.join(site, sub), ignore_errors=True)
    os.makedirs(os.path.join(site, "assets", "img"), exist_ok=True)
    for f in ("style.css", "app.js"):
        shutil.copyfile(os.path.join(ASSETS, f), os.path.join(site, "assets", f))
    custom = os.path.join(w.dir, "custom.css")
    if os.path.exists(custom):
        shutil.copyfile(custom, os.path.join(site, "assets", "custom.css"))
    for e in w.data["entities"].values():
        if e.get("image"):
            src = os.path.join(w.project_root, e["image"])
            if os.path.exists(src):
                shutil.copyfile(src, os.path.join(site, "assets", "img", os.path.basename(src)))
    write_text(os.path.join(site, "assets", "search-index.js"), r.search_index())
    write_text(os.path.join(site, "index.html"), r.render_home())
    write_text(os.path.join(site, "episodes.html"), r.render_episodes_index())
    write_text(os.path.join(site, "timeline.html"), r.render_timeline())
    write_text(os.path.join(site, "glossary.html"), r.render_glossary())
    write_text(os.path.join(site, "threads.html"), r.render_threads())
    write_text(os.path.join(site, "all-pages.html"), r.render_all_pages())
    write_text(os.path.join(site, "history.html"), r.render_history())
    for t in r.types_present():
        write_text(os.path.join(site, "category", "%s.html" % t), r.render_category(t))
    for e in w.data["entities"].values():
        write_text(os.path.join(site, "wiki", "%s.html" % e["id"]), r.render_entity(e))
    eps = r.sorted_eps()
    for i, e in enumerate(eps):
        write_text(os.path.join(site, "episodes", "ep-%s.html" % e["number"]),
                   r.render_episode(e, eps[i - 1] if i else None, eps[i + 1] if i + 1 < len(eps) else None))
    write_text(os.path.join(w.dir, "WIKI-HISTORY.md"), history_markdown(w))


# ------------------------------------------------------------------ cli

def main():
    ap = argparse.ArgumentParser(description="novel-wiki engine " + VERSION)
    ap.add_argument("--wiki", default="wiki", help="wiki directory (default ./wiki)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init")
    p.add_argument("--title", required=True)
    p.add_argument("--tagline")
    p.add_argument("--author")
    p.add_argument("--globs", nargs="+", help="episode file globs relative to the project root")
    p.add_argument("--label", help="what one installment is called: Episode, Chapter, Part ...")
    p.add_argument("--project-root", help="defaults to the wiki folder's parent")
    p.add_argument("--accent", help="CSS colour for the site accent")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)

    sub.add_parser("scan").set_defaults(fn=cmd_scan)
    p = sub.add_parser("brief")
    p.add_argument("--type")
    p.set_defaults(fn=cmd_brief)
    p = sub.add_parser("show")
    p.add_argument("ids", nargs="+")
    p.set_defaults(fn=cmd_show)
    p = sub.add_parser("apply")
    p.add_argument("--patch", nargs="+", required=True)
    p.add_argument("--run-log")
    p.add_argument("--dry-run", action="store_true", help="validate and report warnings without saving")
    p.add_argument("--continue-run", action="store_true",
                   help="fold into the previous history entry (later applies of the same user request)")
    p.set_defaults(fn=cmd_apply)
    p = sub.add_parser("forget")
    p.add_argument("--episode", required=True)
    p.add_argument("--run-log")
    p.set_defaults(fn=cmd_forget)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    p = sub.add_parser("log")
    p.add_argument("--run-log", required=True)
    p.set_defaults(fn=cmd_log)
    sub.add_parser("check").set_defaults(fn=cmd_check)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
