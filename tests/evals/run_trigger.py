"""Windows-safe trigger test: does a fresh `claude -p` session invoke the installed skill?

Usage: python run_trigger.py evals.json out.json --skill novel-wiki --runs 2 --workers 4 --model M
Runs each query in an empty scratch project, watches the stream-json events and
records whether a Skill tool call names the skill. Stops each session early.
"""
import argparse, concurrent.futures as cf, json, os, shutil, subprocess, tempfile, threading, time

ap = argparse.ArgumentParser()
ap.add_argument("evals"); ap.add_argument("out")
ap.add_argument("--skill", required=True); ap.add_argument("--runs", type=int, default=2)
ap.add_argument("--workers", type=int, default=4); ap.add_argument("--model")
ap.add_argument("--timeout", type=int, default=150)
a = ap.parse_args()
CLAUDE = shutil.which("claude")


def one(query):
    proj = tempfile.mkdtemp(prefix="trig-")
    cmd = [CLAUDE, "-p", query, "--output-format", "stream-json", "--verbose", "--max-turns", "4"]
    if a.model:
        cmd += ["--model", a.model]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=proj, env=env)
    result = {"triggered": False, "tools": []}
    killer = threading.Timer(a.timeout, p.kill); killer.start()
    try:
        for raw in p.stdout:
            try:
                ev = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if ev.get("type") != "assistant":
                continue
            for c in ev.get("message", {}).get("content", []):
                if c.get("type") == "tool_use":
                    result["tools"].append(c.get("name"))
                    if c.get("name") == "Skill" and a.skill in json.dumps(c.get("input", {})):
                        result["triggered"] = True
            if result["triggered"] or len(result["tools"]) >= 4:
                break
    finally:
        killer.cancel(); p.kill(); p.wait()
        shutil.rmtree(proj, ignore_errors=True)
    return result


evals = json.load(open(a.evals, encoding="utf-8"))
jobs = [(i, q) for i, q in enumerate(evals) for _ in range(a.runs)]
res = {i: [] for i in range(len(evals))}
with cf.ThreadPoolExecutor(a.workers) as ex:
    for (i, q), r in zip(jobs, ex.map(lambda j: one(j[1]["query"]), jobs)):
        res[i].append(r)
rows, ok = [], 0
for i, q in enumerate(evals):
    rate = sum(r["triggered"] for r in res[i]) / len(res[i])
    passed = (rate >= 0.5) == q["should_trigger"]
    ok += passed
    rows.append({**q, "trigger_rate": rate, "pass": passed, "first_tools": [r["tools"][:3] for r in res[i]]})
out = {"skill": a.skill, "passed": ok, "total": len(evals), "results": rows}
json.dump(out, open(a.out, "w", encoding="utf-8"), indent=2)
print("%d/%d passed" % (ok, len(evals)))
for r in rows:
    print("%s  %-5s rate=%.1f  %s" % ("PASS" if r["pass"] else "FAIL", r["should_trigger"], r["trigger_rate"], r["query"][:80]))
