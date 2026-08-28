# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Korean National University of Education (KNUE) regulation document repository. Markdown versions of official regulations are stored under `규정/` for AI training and RAG systems. `tools/regulations.json` is the master index.

## Key Commands

```bash
# Install/sync Python deps (uv project root is tools/)
cd tools && uv sync && uv run playwright install chromium

# Check website for fileNo changes (read-only)
uv run --project tools python tools/check_updates.py

# Check and apply changes to regulations.json
uv run --project tools python tools/check_updates.py --update

# Parse a regulation preview page → RAW markdown
uv run --project tools python tools/parse_preview.py --file-no <N>

# Convert RAW markdown → repository format
uv run --project tools python tools/reformat_regulation.py \
  --raw /tmp/raw_<N>.md --reg-name "<규정명>" --out "<DEST>"
```

To process pending GitHub issues from the weekly workflow, use the `/update-regulations` skill.

## Architecture

### Data Model

`tools/regulations.json` has three top-level keys:
- `source_url` — KNUE website to scrape
- `last_checked` — ISO timestamp of last check
- `regulations` — array of `{ name, file_no, section, domain, audience, local_path }`,
  plus optional `official_name`

`local_path` maps to `규정/<section>/<name>.md`. `section` follows the `제N편/제N장` hierarchy.

`section` is the official codebook hierarchy and does not track who a regulation binds or
which office owns it, so two orthogonal tags are stored alongside it:
- `domain` — single business area (학사·교육과정, 연구·산학, 교원인사, …)
- `audience` — one or more bound parties (학부생, 대학원생, 전임교원, 교직원, …)

Allowed values live in `tools/taxonomy.py` (`DOMAINS` / `AUDIENCES`) — the single source of
truth. `check_quality.py` fails on a missing or off-vocabulary tag, and `check_updates.py`
seeds new entries with empty tags so the gate catches them.

`name` is the KNUE site's list label. When a regulation's own title differs from that label,
record the document's title in `official_name` — `check_quality.py` compares the title line
inside the markdown against it.

**Site list labels are not trustworthy.** The `<a title=...>` attribute sometimes carries the
previous row's name, so two fileNos can surface under one name (fileNo 1596 is 「교수회 규정」
but is listed as 「교수회평의회 규정」). `check_updates.py` warns on duplicate titles; always
confirm the real name from the preview body before registering a new regulation, or the new
file will overwrite an existing one.

### Regulation Update Pipeline

```
KNUE website → check_updates.py → GitHub issues (regulation-update label)
                                  → regulations.json pre-updated by CI
  → update-regulations skill → parse_preview.py → reformat_regulation.py
                             → markdown file + regulations.json local_path/section update
                             → commit on regulation-sync/YYYY-MM-DD branch
```

The CI workflow (`check-regulation-updates.yml`, runs Monday 00:00 UTC) creates issues **and** immediately runs `check_updates.py --update` to pre-update `regulations.json`. By the time the skill processes issues, `regulations.json` already has updated `file_no` values — only the markdown files and `section`/`local_path` fields remain to be filled in by the skill.

### Regulation File Format

Files use the convention: `규정/<section>/<name>.md`

Expected structure after `reformat_regulation.py`:
- First line: `# <규정명>`
- Enforcement history lines (공포/개정) before `---` divider
- `## 제N장` for chapters, `## 제N절` for sections
- `## 제N조(조문제목)` or `### 제N조(조문제목)` for articles (three `#` when chapters exist)
- `## 부칙`, `## 별표`, etc. for appendices (`### 부칙` etc. when chapters exist, matching article level)

Quality gate: first line starts with `# <REG_NAME>`, file ≥ 500 chars, at least one `## ` header.

### Tools

| File | Role |
|------|------|
| `tools/check_updates.py` | Scrapes KNUE site, diffs against `regulations.json`, optionally applies changes |
| `tools/parse_preview.py` | Playwright headless scraper: preview URL → RAW markdown |
| `tools/reformat_regulation.py` | Rule-based RAW → repository format converter |
| `tools/taxonomy.py` | `domain`/`audience` allowed-value vocabulary (SSOT) |
| `tools/check_quality.py` | JSON integrity + taxonomy + markdown quality gate (CI) |

## Docs

| File | Role |
|------|------|
| `docs/rag-agent-prompt.md` | System prompt for the KNUE regulation RAG agent, plus chunking notes. Keep its 축 1/축 2 values in sync with `tools/taxonomy.py`. |

## Branching

The `update-regulations` skill creates `regulation-sync/YYYY-MM-DD` branches. All regulation content work goes through that pattern. The automated CI bot commits `regulations.json` updates directly to `main`.
