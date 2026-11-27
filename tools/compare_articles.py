"""Compare two versions of one regulation Markdown file article by article.

Pairs articles by the article number in the body headings (제3조, 제3조의2) and
writes a local HTML table of the added, deleted and modified articles only.
부칙·별표·별지 are not compared, and an article whose number changed is never
presumed to be the same article: it shows up as one deletion plus one addition.
This is a review aid, not the official 신구조문대비표.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from reformat_regulation import _APPENDIX_RE, _CHAPTER_RE, _SECTION_RE

_HEADER_RE = re.compile(r"^#{1,6}\s+(.*?)\s*$")
# 제N조 / 제N조의M — the source sometimes writes "제4조의 2".
_ARTICLE_HEAD_RE = re.compile(r"^(제\d+조(?:의\s*\d+)?)(.*)$")

ADDED, DELETED, MODIFIED = "추가", "삭제", "수정"


@dataclass(frozen=True)
class Article:
    number: str
    text: str  # normalized: heading remainder + body lines, one per line


@dataclass(frozen=True)
class Change:
    kind: str
    number: str
    old: str
    new: str


def _normalize_number(raw: str) -> str:
    return re.sub(r"\s+", "", raw)


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def parse_articles(text: str, source: str = "input") -> tuple[str, dict[str, Article]]:
    """Return (H1 title, articles in document order).

    Raises ValueError when one article number appears twice, because pairing by
    number would then be ambiguous.
    """
    title = ""
    articles: dict[str, Article] = {}
    current: tuple[str, list[str]] | None = None
    in_appendix = False

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        number, lines = current
        if number in articles:
            raise ValueError(f"{source}: duplicate article number {number}")
        body = [ln for ln in (_normalize_line(x) for x in lines) if ln]
        articles[number] = Article(number, "\n".join(body))
        current = None

    for raw in text.splitlines():
        header = _HEADER_RE.match(raw)
        if header is None:
            if current is not None:
                current[1].append(raw)
            continue
        head = header.group(1)
        if raw.startswith("# ") and not title:
            title = head
            continue
        if _APPENDIX_RE.match(head):
            flush()
            in_appendix = True
            continue
        if _CHAPTER_RE.match(head) or _SECTION_RE.match(head):
            flush()
            in_appendix = False
            continue
        match = _ARTICLE_HEAD_RE.match(head)
        if match is None or in_appendix:
            # Other headings keep belonging to the current block; inside an
            # appendix everything is skipped, article-like headings included.
            if current is not None and not in_appendix:
                current[1].append(raw)
            continue
        flush()
        current = (_normalize_number(match.group(1)), [match.group(2)])
    flush()
    return title, articles


def diff_articles(old: dict[str, Article], new: dict[str, Article]) -> list[Change]:
    """Added, deleted and modified articles; unchanged ones are omitted."""
    changes: list[Change] = []
    for number, article in old.items():
        other = new.get(number)
        if other is None:
            changes.append(Change(DELETED, number, article.text, ""))
        elif other.text != article.text:
            changes.append(Change(MODIFIED, number, article.text, other.text))
    for number, article in new.items():
        if number not in old:
            changes.append(Change(ADDED, number, "", article.text))
    return sorted(changes, key=lambda c: _sort_key(c.number))


def _sort_key(number: str) -> tuple[int, int]:
    m = re.match(r"제(\d+)조(?:의(\d+))?", number)
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)


_CSS = """
body{font-family:'Malgun Gothic',sans-serif;margin:2rem;color:#222}
table{border-collapse:collapse;width:100%;table-layout:fixed}
th,td{border:1px solid #bbb;padding:.5rem;vertical-align:top;text-align:left}
th{background:#f0f0f0}
td.text{white-space:pre-wrap;word-break:break-word}
td.kind{width:5rem}td.num{width:8rem}
tr.added td.kind{background:#e6f4ea}tr.deleted td.kind{background:#fce8e6}
tr.modified td.kind{background:#fef7e0}
.notice{background:#f6f6f6;border-left:4px solid #888;padding:.5rem 1rem;margin:1rem 0}
"""

_KIND_CLASS = {ADDED: "added", DELETED: "deleted", MODIFIED: "modified"}


def render_html(
    changes: list[Change],
    old_label: str,
    new_label: str,
    old_title: str = "",
    new_title: str = "",
) -> str:
    e = html.escape
    counts = {k: sum(1 for c in changes if c.kind == k) for k in (MODIFIED, ADDED, DELETED)}
    rows = []
    for c in changes:
        rows.append(
            f'<tr class="{_KIND_CLASS[c.kind]}"><td class="kind">{e(c.kind)}</td>'
            f'<td class="num">{e(c.number)}</td>'
            f'<td class="text">{e(c.old)}</td><td class="text">{e(c.new)}</td></tr>'
        )
    if not rows:
        rows.append('<tr><td colspan="4">바뀐 조문이 없습니다.</td></tr>')
    notices = [
        "이 표는 검토 보조용이며 공식 신구조문대비표를 대체하지 않습니다.",
        "본문 조문 번호로만 짝을 맞춥니다. 조문 번호가 바뀐 경우 같은 조문으로 추정하지 않고 "
        "삭제와 추가로 각각 표시합니다.",
        "부칙·별표·별지는 비교 대상에서 제외했습니다. 미변경 조문은 표시하지 않습니다.",
    ]
    if old_title and new_title and old_title != new_title:
        notices.append(f"주의: 두 파일의 규정명이 다릅니다 ({old_title} / {new_title}).")
    return (
        '<!DOCTYPE html>\n<html lang="ko"><head><meta charset="utf-8">'
        "<title>조문별 신구 검토표</title>"
        f"<style>{_CSS}</style></head><body>\n"
        f"<h1>{e(new_title or old_title or '규정')} 조문별 신구 검토표</h1>\n"
        f"<p>이전: {e(old_label)}<br>이후: {e(new_label)}</p>\n"
        f"<p>수정 {counts[MODIFIED]}건 · 추가 {counts[ADDED]}건 · 삭제 {counts[DELETED]}건</p>\n"
        + "".join(f'<p class="notice">{e(n)}</p>\n' for n in notices)
        + "<table><thead><tr><th>구분</th><th>조문</th><th>이전</th><th>이후</th></tr></thead>\n<tbody>\n"
        + "\n".join(rows)
        + "\n</tbody></table>\n</body></html>\n"
    )


def compare_files(old_path: Path, new_path: Path) -> str:
    old_title, old_articles = parse_articles(old_path.read_text(encoding="utf-8"), str(old_path))
    new_title, new_articles = parse_articles(new_path.read_text(encoding="utf-8"), str(new_path))
    return render_html(
        diff_articles(old_articles, new_articles),
        str(old_path), str(new_path), old_title, new_title,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Show only the changed articles between two versions of a regulation Markdown file."
    )
    parser.add_argument("old", type=Path, help="older Markdown file")
    parser.add_argument("new", type=Path, help="newer Markdown file")
    parser.add_argument("--out", type=Path, help="HTML output path (default: stdout)")
    args = parser.parse_args(argv)
    try:
        page = compare_files(args.old, args.new)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.out:
        args.out.write_text(page, encoding="utf-8")
    else:
        sys.stdout.buffer.write(page.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
