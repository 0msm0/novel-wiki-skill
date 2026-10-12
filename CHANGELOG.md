# Changelog

## 1.0.0 (2026-10-12)

First release.

- `update wiki` workflow: scan for new or revised episodes, read each in full, write one patch per episode, apply, check, report.
- Engine (`scripts/wiki.py`, stdlib only): `init`, `scan`, `brief`, `show`, `apply` (with `--dry-run` and `--continue-run`), `forget`, `build`, `log`, `check`.
- Revised episodes are rolled back and re-applied; pages, threads and terms the revision drops are removed.
- Editorial corrections are sticky (locked fields with warnings, `unlock` to release).
- Static site: articles with infoboxes and per-episode history, episode guide, timeline, mysteries tracker, glossary, all-pages index, search, spoiler filter, dark/light mode, mobile layout.
- Run history in `data/history.json`, `site/history.html` and `WIKI-HISTORY.md`.
- Fan-wiki style guide and patch reference in `references/`.
- Example project (live demo on GitHub Pages), 14 engine regression tests, behavioural and trigger evals, CI on Linux/macOS/Windows.
