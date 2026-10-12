"""Programmatic grader for novel-wiki evals. Usage: python grade.py <run_dir> <eval_id> [<fixture_dir>]"""
import glob, hashlib, json, os, re, sys

run, eid = sys.argv[1], int(sys.argv[2])
proj = os.path.join(run, "project")
FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def files(exts=(".html", ".md", ".json")):
    out = []
    for p in glob.glob(os.path.join(proj, "**", "*"), recursive=True):
        rel = os.path.relpath(p, proj).replace("\\", "/")
        if os.path.isfile(p) and p.endswith(exts) and not rel.startswith("chapters/") and rel != "README.md":
            out.append((rel, open(p, encoding="utf-8", errors="replace").read()))
    return out


def text(s):
    s = re.sub(r"<script.*?</script>|<style.*?</style>", " ", s, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))


F = files()
HTML = [(r, c) for r, c in F if r.endswith(".html")]
ALL = " ".join(text(c) for _, c in F)
reply = ""
rp = os.path.join(run, "outputs", "final_reply.md")
if os.path.exists(rp):
    reply = open(rp, encoding="utf-8").read()


def page_for(name):
    """HTML pages whose <h1> is the name."""
    hits = []
    for r, c in HTML:
        m = re.search(r"<h1[^>]*>(.*?)</h1>", c, re.S)
        if m and name.lower() in text(m.group(1)).lower():
            hits.append(r)
    return hits


def history_text():
    return " ".join(c for r, c in F if re.search(r"history|changelog|log", r, re.I))


def chapters_untouched():
    ok = True
    for p in glob.glob(os.path.join(proj, "chapters", "*.md")):
        base = os.path.basename(p)
        cands = glob.glob(os.path.join(FIX, "**", base), recursive=True) + \
            glob.glob(os.path.join(FIX, "**", base.replace(".md", ".REVISED.md")), recursive=True)
        h = lambda f: hashlib.md5(open(f, "rb").read().replace(b"\r\n", b"\n")).hexdigest()
        if cands and h(p) not in {h(c) for c in cands}:
            ok = False
    return ok


R = []


def check(name, passed, evidence):
    R.append({"text": name, "passed": bool(passed), "evidence": evidence})


if eid == 1:
    idx = [r for r, _ in HTML if r.endswith("index.html")]
    check("Produces an HTML wiki site (an index.html)", idx, ", ".join(idx[:3]) or "none")
    for n in ("Mira Osk", "Tobin Reed", "Seren", "Varr Dane"):
        p = page_for(n)
        check("Has a dedicated page for %s" % n, p, ", ".join(p) or "no page with that title")
    dup = page_for("hooded woman")
    check("Hooded woman is not a separate page from Seren", not dup, ", ".join(dup) or "no separate page")
    e1, e2 = page_for("Brass Thief"), page_for("Salt Barge")
    check("Each episode has its own page", e1 and e2, "ep1: %s; ep2: %s" % (e1, e2))
    h = history_text()
    check("Usage history exists and names the chapter files read", "01-the-brass-thief" in h and "02-the-salt-barge" in h,
          "history files: %s" % [r for r, _ in F if re.search(r"history|changelog|log", r, re.I)][:5])
    check("Tidecalling's memory cost is recorded", re.search(r"tidecall\w*.{0,400}memor|memor.{0,400}tidecall", ALL, re.I | re.S),
          "searched all wiki text")
    m = re.search(r".{0,80}scar.{0,80}", ALL, re.I)
    check("Burn scar placed on her right palm (canon accuracy)", re.search(r"right (palm|hand)[^.]{0,60}scar|scar[^.]{0,60}right (palm|hand)", ALL, re.I),
          m.group(0) if m else "no scar mention")
    check("Manuscript chapters untouched", chapters_untouched(), "hash compare with fixtures")

if eid == 2:
    e3 = page_for("What the Water Keeps")
    check("Episode 3 has a page", e3, ", ".join(e3) or "none")
    e2 = page_for("Salt Barge")
    check("Exactly one Episode 2 page (revised in place)", len(e2) == 1, ", ".join(e2) or "none")
    ep2 = text(open(os.path.join(proj, e2[0]), encoding="utf-8").read()) if e2 else ""
    check("Episode 2 page reflects the revision (mentions Pell)", "Pell" in ep2, ep2[:0] or ("Pell found" if "Pell" in ep2 else "Pell missing"))
    stale = re.search(r"Tobin[^.]{0,120}(captured|hauled|taken by the wardens|seized|arrested)|(captured|hauled|seized)[^.]{0,60}Tobin", ep2, re.I)
    if stale and re.search(r"instead of|no longer|not |rather than", stale.group(0), re.I):
        stale = None
    check("Episode 2 no longer says Tobin was captured", not stale, stale.group(0) if stale else "no capture wording")
    p = page_for("Pell")
    check("Pell has a page", p, ", ".join(p) or "none")
    flag = re.search(r"continuity|contradict|inconsisten|conflict", reply + " " + history_text(), re.I)
    check("Flags the Tobin continuity clash between revised Ep2 and Ep3", flag, flag.group(0) if flag else "no flag in reply or history")
    h = history_text()
    runs = len(re.findall(r"Run #\d+|^## ", h, re.M))
    check("History records the new run alongside the first", "03-what-the-water-keeps" in h, "chapter 3 file named in history: %s" % ("03-what-the-water-keeps" in h))
    check("Manuscript chapters untouched", chapters_untouched(), "hash compare with fixtures")

if eid == 3:
    mp = page_for("Mira Osk")
    mt = text(open(os.path.join(proj, mp[0]), encoding="utf-8").read()) if mp else ""
    check("Mira's page shows age 20", re.search(r"\b20\b", mt), "page: %s" % mp)
    check("Mira's page no longer shows age 19", not re.search(r"Age\s*19|19[- ]year", mt), "")
    pp = page_for("Bettany")
    pt = open(os.path.join(proj, pp[0]), encoding="utf-8").read() if pp else ""
    home = next((c for r, c in HTML if r.endswith("site/index.html") or r == "index.html" or r.endswith("wiki/index.html")), "")
    check("Bettany marked as a major/main character", re.search(r"major|main", text(pt), re.I) or ("Bettany" in text(home)),
          "pell page: %s" % pp)
    h = history_text()
    check("History records the correction", re.search(r"(Bettany|age|20).{0,200}", h) and re.search(r"correct|edit|fix", h, re.I), "")
    check("Manuscript chapters untouched", chapters_untouched(), "hash compare with fixtures")

passed = sum(r["passed"] for r in R)
out = {"expectations": R, "summary": {"passed": passed, "failed": len(R) - passed, "total": len(R),
                                      "pass_rate": round(passed / len(R), 2) if R else 0}}
json.dump(out, open(os.path.join(run, "grading.json"), "w"), indent=2)
print(json.dumps(out["summary"]), [r["text"] for r in R if not r["passed"]])
