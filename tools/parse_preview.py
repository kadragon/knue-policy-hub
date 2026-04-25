"""KNUE 규정 미리보기 파서.

knue-www-preview-parser-cf(Cloudflare Worker + Puppeteer)의 파싱 로직을
Python + Playwright(chromium headless)로 포팅한다.

URL 규칙: https://www.knue.ac.kr/www/previewMenuCntFile.do?key=392&fileNo={file_no}
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass

from playwright.sync_api import Error as PlaywrightError, sync_playwright

PREVIEW_URL = "https://www.knue.ac.kr/www/previewMenuCntFile.do?key=392&fileNo={file_no}"
NAVIGATE_TIMEOUT_MS = 30_000
POST_LOAD_WAIT_MS = 5_000
MAX_SCROLL_PX = 100_000
SCROLL_STEP_PX = 800
STABLE_CONTENT_STREAK = 8  # consecutive same content-length readings before declaring done

FULLWIDTH_DIGITS = "０１２３４５６７８９"
H2_PREFIX_RE = re.compile(rf"^[{FULLWIDTH_DIGITS}]+\s+")
H1_BRACKET_RE = re.compile(r"^【(.+)】\s*$")
HR_RE = re.compile(r"^=+$")
BULLET_RE = re.compile(r"^[ㆍ‣○□]\s*")
TABLE_SPLIT_RE = re.compile(r"\s{2,}")


@dataclass
class ParseResult:
    file_no: int
    markdown: str


def _extract_lines(page) -> list[str]:
    """iframe#innerWrap > #content_body 에서 줄 배열을 뽑는다.

    innerText 는 요소의 layout 범위(overflow 등)에 의존하므로 대신 DOM 을 직접
    순회하여 블록 요소 경계마다 줄바꿈을 삽입한 뒤 전체 텍스트를 추출한다.
    """
    text: str = page.evaluate(
        """() => {
            const BLOCK_TAGS = new Set([
                'P','DIV','LI','TR','TD','TH','CAPTION','ARTICLE','SECTION',
                'HEADER','FOOTER','H1','H2','H3','H4','H5','H6',
                'BLOCKQUOTE','PRE','TABLE','THEAD','TBODY','TFOOT','BR',
            ]);
            function walk(node) {
                if (node.nodeType === 3) return node.nodeValue || '';
                if (node.nodeType !== 1) return '';
                const tag = (node.tagName || '').toUpperCase();
                if (tag === 'SCRIPT' || tag === 'STYLE') return '';
                const isBlock = BLOCK_TAGS.has(tag);
                let text = isBlock ? '\\n' : '';
                for (const child of node.childNodes) text += walk(child);
                if (isBlock) text += '\\n';
                return text;
            }
            const iframe = document.querySelector('iframe#innerWrap');
            if (!iframe) return '';
            const doc = iframe.contentDocument;
            if (!doc) return '';
            const body = doc.querySelector('#content_body');
            if (!body) return '';
            return walk(body);
        }"""
    )
    return [line.strip() for line in text.splitlines() if line.strip()]


def _scroll_to_bottom(page) -> None:
    """끝까지 스크롤해 lazy-load 콘텐츠를 모두 가져온다.

    scrollHeight 대신 #content_body 텍스트 길이로 안정성을 판단한다.
    scrollHeight 는 lazy-load 트리거 전 초기 상태에서도 변하지 않아 조기 종료를
    유발하지만, 텍스트 길이는 실제로 새 콘텐츠가 추가될 때만 변한다.
    """
    last_lengths: list[int] = []
    total = 0
    while total < MAX_SCROLL_PX:
        content_len: int = page.evaluate(
            """() => {
                const iframe = document.querySelector('iframe#innerWrap');
                if (iframe && iframe.contentDocument) {
                    const body = iframe.contentDocument.querySelector('#content_body');
                    if (body) return body.textContent.length;
                    return iframe.contentDocument.body.textContent.length;
                }
                return document.body.textContent.length;
            }"""
        )
        last_lengths.append(content_len)
        if len(last_lengths) >= STABLE_CONTENT_STREAK and len(set(last_lengths[-STABLE_CONTENT_STREAK:])) == 1:
            break
        page.evaluate(
            f"""() => {{
                const iframe = document.querySelector('iframe#innerWrap');
                if (iframe && iframe.contentDocument && iframe.contentDocument.defaultView) {{
                    iframe.contentDocument.defaultView.scrollBy(0, {SCROLL_STEP_PX});
                }} else {{
                    window.scrollBy(0, {SCROLL_STEP_PX});
                }}
            }}"""
        )
        page.wait_for_timeout(200)
        total += SCROLL_STEP_PX
    else:
        print(
            f"WARN: scroll cap reached ({MAX_SCROLL_PX}px) — content may be truncated",
            file=sys.stderr,
        )


def _flush_table(buffer: list[list[str]], out: list[str]) -> None:
    if not buffer:
        return
    cols = max(len(row) for row in buffer)
    if cols < 2 or len(buffer) < 2:
        for row in buffer:
            out.append(" ".join(row))
        buffer.clear()
        return
    normalized = [row + [""] * (cols - len(row)) for row in buffer]
    header, *rest = normalized
    out.append("| " + " | ".join(header) + " |")
    out.append("|" + "|".join(["---"] * cols) + "|")
    for row in rest:
        out.append("| " + " | ".join(row) + " |")
    buffer.clear()


def convert_to_markdown(lines: list[str]) -> str:
    """중간 마크다운 생성. AI 재포맷 전의 raw 형태."""
    out: list[str] = []
    table_buf: list[list[str]] = []

    for raw in lines:
        if TABLE_SPLIT_RE.search(raw) and not H1_BRACKET_RE.match(raw) and not H2_PREFIX_RE.match(raw):
            table_buf.append([c.strip() for c in TABLE_SPLIT_RE.split(raw) if c.strip()])
            continue
        _flush_table(table_buf, out)

        if HR_RE.match(raw):
            out.append("---")
            continue
        m1 = H1_BRACKET_RE.match(raw)
        if m1:
            out.append(f"# {m1.group(1).strip()}")
            continue
        m2 = H2_PREFIX_RE.match(raw)
        if m2:
            out.append(f"## {raw[m2.end():].strip()}")
            continue
        if BULLET_RE.match(raw):
            out.append(f"- {BULLET_RE.sub('', raw)}")
            continue
        out.append(raw)

    _flush_table(table_buf, out)

    joined = "\n".join(out)
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return joined.strip() + "\n"


def parse_preview(file_no: int, headless: bool = True) -> ParseResult:
    url = PREVIEW_URL.format(file_no=file_no)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=NAVIGATE_TIMEOUT_MS)
            page.wait_for_timeout(POST_LOAD_WAIT_MS)
            _scroll_to_bottom(page)
            lines = _extract_lines(page)
        finally:
            browser.close()
    if not lines:
        raise RuntimeError(f"미리보기에서 본문을 추출하지 못했습니다 (fileNo={file_no})")
    return ParseResult(file_no=file_no, markdown=convert_to_markdown(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="KNUE 규정 미리보기 파서")
    parser.add_argument("--file-no", type=int, required=True, help="regulations.json 의 file_no (미리보기 URL fileNo)")
    parser.add_argument("--no-headless", action="store_true", help="디버그용: 브라우저 창 표시")
    args = parser.parse_args()
    try:
        result = parse_preview(args.file_no, headless=not args.no_headless)
    except (RuntimeError, PlaywrightError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    sys.stdout.write(result.markdown)


if __name__ == "__main__":
    main()
