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

_TBL_START = "<<<TBL>>>"
_TBL_END = "<<</TBL>>>"


@dataclass
class ParseResult:
    file_no: int
    markdown: str


def _extract_lines(page) -> list[str]:
    """iframe#innerWrap > #content_body 에서 줄 배열을 뽑는다.

    innerText 는 요소의 layout 범위(overflow 등)에 의존하므로 대신 DOM 을 직접
    순회하여 블록 요소 경계마다 줄바꿈을 삽입한 뒤 전체 텍스트를 추출한다.

    <table> 요소는 일반 블록 처리에서 제외하고 extractTable() 로 위임해
    마크다운 표 구조를 보존한다. sentinel(<<<TBL>>>…<<</TBL>>>)로 감싸
    convert_to_markdown() 에서 그대로 통과시킨다.
    """
    text: str = page.evaluate(
        """() => {
            const BLOCK_TAGS = new Set([
                'P','DIV','LI','TR','TD','TH','CAPTION','ARTICLE','SECTION',
                'HEADER','FOOTER','H1','H2','H3','H4','H5','H6',
                'BLOCKQUOTE','PRE','THEAD','TBODY','TFOOT','BR',
            ]);
            function cellText(td) {
                return (td.textContent || '').replace(/\\s+/g, ' ').trim().replace(/\\|/g, '\\\\|');
            }
            function collectRows(tbl) {
                const rows = [];
                for (const child of tbl.children) {
                    const ct = (child.tagName || '').toUpperCase();
                    if (ct === 'TR') {
                        rows.push(child);
                    } else if (ct === 'THEAD' || ct === 'TBODY' || ct === 'TFOOT') {
                        for (const tr of child.children) {
                            if ((tr.tagName || '').toUpperCase() === 'TR') rows.push(tr);
                        }
                    }
                }
                return rows;
            }
            // Depth of a grouped header band at the top of the table, or 1 when there is
            // none. Fold only when the band is unambiguously a header: every row-0 cell
            // either spans the whole band or is a group (colspan) with labels below it,
            // the rows inside the band hold only non-empty, non-numeric labels under those
            // groups, and nothing in the band spills into the first body row. Anything
            // less certain stays unfolded, so a row-0 label that groups data rows (e.g.
            // 「1학년」 rowspan over course rows) is never swallowed into the header.
            function headerDepth(head, src, full) {
                const depth = Math.max(1, ...head.map(h => h.rs));
                if (depth < 2 || depth >= full.length) return 1;
                if (head.some(h => h.rs !== depth && h.cs < 2)) return 1;
                const groupCols = new Set();
                for (const h of head) {
                    if (h.rs < depth) for (let dc = 0; dc < h.cs; dc++) groupCols.add(h.c + dc);
                }
                if (!groupCols.size) return 1;
                for (let r = 1; r < depth; r++) {
                    for (let c = 0; c < full[r].length; c++) {
                        if (src[r][c] === 0) continue;
                        if (!groupCols.has(c) || /^[\\d\\s.,%~+-]*$/.test(full[r][c])) return 1;
                    }
                }
                if (src[depth].some(s => s !== depth)) return 1;
                return depth;
            }
            function extractTable(table) {
                const rows = collectRows(table);
                if (!rows.length) return '';
                // Expand rowspan/colspan into a grid, repeating the spanned text in every
                // slot it covers so each markdown row stays self-contained and columns line
                // up with multi-row headers. Without this, spanned cells shift left.
                const grid = [];
                const src = [];  // src[r][c]: row index where the cell covering (r, c) starts
                const own = [];  // own[r]: row r has at least one non-empty originating cell
                const head = []; // row-0 cells: {c, rs, cs}
                rows.forEach((tr, r) => {
                    grid[r] = grid[r] || [];
                    src[r] = src[r] || [];
                    let c = 0;
                    for (const cell of tr.children) {
                        const ct = (cell.tagName || '').toUpperCase();
                        if (ct !== 'TD' && ct !== 'TH') continue;
                        while (grid[r][c] !== undefined) c++;
                        const text = cellText(cell);
                        if (text) own[r] = true;
                        const rs = Math.max(1, cell.rowSpan || 1);
                        const cs = Math.max(1, cell.colSpan || 1);
                        if (r === 0) head.push({c, rs, cs});
                        for (let dr = 0; dr < rs && r + dr < rows.length; dr++) {
                            grid[r + dr] = grid[r + dr] || [];
                            src[r + dr] = src[r + dr] || [];
                            for (let dc = 0; dc < cs; dc++) {
                                grid[r + dr][c + dc] = text;
                                src[r + dr][c + dc] = r;
                            }
                        }
                        c += cs;
                    }
                });
                const full = grid.map(row => Array.from(row, v => v === undefined ? '' : v));
                const depth = headerDepth(head, src, full);
                let data = [];
                if (depth > 1) {
                    // Grouped header (e.g. 「하사관」 over 상사/중사/하사): markdown allows
                    // one header row, so fold the band, joining each column's distinct labels.
                    const width = Math.max(...full.slice(0, depth).map(r => r.length));
                    const folded = [];
                    for (let c = 0; c < width; c++) {
                        const parts = [];
                        for (const row of full.slice(0, depth)) {
                            const v = row[c] || '';
                            if (v && !parts.includes(v)) parts.push(v);
                        }
                        folded.push(parts.join(' / '));
                    }
                    data.push(folded);
                }
                // Drop rows that add nothing of their own (only span leftovers or blanks).
                const bodyStart = depth > 1 ? depth : 0;
                full.forEach((row, r) => { if (r >= bodyStart && own[r]) data.push(row); });
                if (!data.length) return '';
                const cols = Math.max(...data.map(r => r.length));
                const norm = data.map(r => [...r, ...Array(cols - r.length).fill('')]);
                const mdLines = [];
                mdLines.push('| ' + norm[0].join(' | ') + ' |');
                mdLines.push('|' + Array(cols).fill('---').join('|') + '|');
                for (const row of norm.slice(1)) {
                    mdLines.push('| ' + row.join(' | ') + ' |');
                }
                return '\\n<<<TBL>>>\\n' + mdLines.join('\\n') + '\\n<<</TBL>>>\\n';
            }
            function walk(node) {
                if (node.nodeType === 3) return node.nodeValue || '';
                if (node.nodeType !== 1) return '';
                const tag = (node.tagName || '').toUpperCase();
                if (tag === 'SCRIPT' || tag === 'STYLE') return '';
                if (tag === 'TABLE') return extractTable(node);
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
    # Require 2+ cols, 2+ rows, and uniform column count to prevent false positives
    # from whitespace-padded plain text (e.g. kerned Korean department names).
    all_same_cols = all(len(row) == cols for row in buffer)
    if cols < 2 or len(buffer) < 2 or not all_same_cols:
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
    # Pre-pass: reassemble HTML-extracted table blocks (sentinel <<<TBL>>> … <<</TBL>>>)
    # into list objects so the main loop can emit them verbatim without heuristic interference.
    coalesced: list[str | list[str]] = []
    in_tbl = False
    tbl_lines: list[str] = []
    for line in lines:
        if line == _TBL_START:
            in_tbl = True
            tbl_lines = []
        elif line == _TBL_END:
            in_tbl = False
            if tbl_lines:
                coalesced.append(tbl_lines[:])
        elif in_tbl:
            tbl_lines.append(line)
        else:
            coalesced.append(line)

    out: list[str] = []
    table_buf: list[list[str]] = []

    for item in coalesced:
        if isinstance(item, list):
            _flush_table(table_buf, out)
            out.extend(item)
            continue

        raw: str = item
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
