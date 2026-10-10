"""KNUE 규정 미리보기 파서.

knue-www-preview-parser-cf(Cloudflare Worker + Puppeteer)의 파싱 로직을
Python + Playwright(chromium headless)로 포팅한다.

URL 규칙: https://www.knue.ac.kr/www/previewMenuCntFile.do?key=392&fileNo={file_no}
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from tempfile import TemporaryDirectory
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError, sync_playwright

PREVIEW_URL = "https://www.knue.ac.kr/www/previewMenuCntFile.do?key=392&fileNo={file_no}"
DOWNLOAD_URL = "https://www.knue.ac.kr/downloadContentsFile.do?key=392&fileNo={file_no}"
HWP_CONVERT_TIMEOUT_SECONDS = 120
NAVIGATE_TIMEOUT_MS = 30_000
POST_LOAD_WAIT_MS = 5_000
CONTENT_LOAD_TIMEOUT_MS = 60_000

FULLWIDTH_DIGITS = "０１２３４５６７８９"
H2_PREFIX_RE = re.compile(rf"^[{FULLWIDTH_DIGITS}]+\s+")
H1_BRACKET_RE = re.compile(r"^【(.+)】\s*$")
HR_RE = re.compile(r"^=+$")
BULLET_RE = re.compile(r"^[ㆍ‣○□]\s*")
TABLE_SPLIT_RE = re.compile(r"\s{2,}")

# The DOM → text/table extractor lives in its own file so tests can run it against local
# HTML fixtures (tools/tests/test_extract_body.py).
EXTRACT_BODY_JS = (Path(__file__).resolve().parent / "extract_body.js").read_text(encoding="utf-8")

# Exact first-row label pieces verified in the finance preview (fileNo 1693).
# Evidence and extension rules: docs/table-parser-followups.md. Never infer these
# corrections from cell width or apply them to unrelated source documents.
CONFIRMED_WRAPPED_HEADERS = {
    1693: [["입학인재", "관리과"]],
}

_TBL_START = "<<<TBL>>>"
_TBL_END = "<<</TBL>>>"


@dataclass
class ParseResult:
    file_no: int
    markdown: str


def _extract_lines(page, file_no: int | None = None) -> list[str]:
    """iframe#innerWrap > #content_body 에서 줄 배열을 뽑는다.

    innerText 는 요소의 layout 범위(overflow 등)에 의존하므로 대신 DOM 을 직접
    순회하여 블록 요소 경계마다 줄바꿈을 삽입한 뒤 전체 텍스트를 추출한다.

    <table> 요소는 일반 블록 처리에서 제외하고 extractTable() 로 위임해
    마크다운 표 구조를 보존한다. sentinel(<<<TBL>>>…<<</TBL>>>)로 감싸
    convert_to_markdown() 에서 그대로 통과시킨다.
    """
    text: str = page.evaluate(
        f"""(confirmedLabels) => {{
            const extractBody = {EXTRACT_BODY_JS};
            const iframe = document.querySelector('iframe#innerWrap');
            if (!iframe) return '';
            const doc = iframe.contentDocument;
            if (!doc) return '';
            const body = doc.querySelector('#content_body');
            if (!body) return '';
            return extractBody(body, confirmedLabels);
        }}""",
        CONFIRMED_WRAPPED_HEADERS.get(file_no, []),
    )
    return [line.strip() for line in text.splitlines() if line.strip()]


def _wait_for_completion(page) -> None:
    """Reject partial viewer output even when its text length has stopped growing."""
    page.wait_for_function(
        """() => {
            const iframe = document.querySelector('iframe#innerWrap');
            return iframe?.contentWindow?.localSynap?.completed === 1;
        }""",
        timeout=CONTENT_LOAD_TIMEOUT_MS,
    )


def _verify_hwp_text(paragraphs: list[str], text: str, *, markdown: bool = False) -> None:
    """Reject missing source paragraphs, including repeated table-cell values."""
    def normalize(value):
        return re.sub(r"\s+", "", value.replace("\\|", "|"))

    expected = Counter()
    for paragraph in paragraphs:
        # Table blocks retain literal bullets; ordinary prose may turn them into
        # Markdown lists. Both representations must reserve their own output span.
        forms = [normalize(paragraph)]
        if markdown:
            forms.append(normalize(convert_to_markdown([paragraph])))
        expected[tuple(dict.fromkeys(form for form in forms if form))] += 1
    remaining = normalize(text)
    if not expected:
        raise RuntimeError("HWP source text missing from recovered content")
    # Match longer paragraphs first so their embedded words cannot also satisfy
    # missing standalone cells. Mask consumed spans without joining their neighbors.
    for forms, count in sorted(expected.items(), key=lambda item: max(map(len, item[0]), default=0), reverse=True):
        for _ in range(count):
            for form in forms:
                index = remaining.find(form)
                if index >= 0:
                    remaining = remaining[:index] + "\0" * len(form) + remaining[index + len(form):]
                    break
            else:
                raise RuntimeError("HWP source text missing from recovered content")


def _recover_hwp(page, file_no: int) -> list[str]:
    """Recover only from the official download for the same file number."""
    response = page.request.get(DOWNLOAD_URL.format(file_no=file_no), timeout=NAVIGATE_TIMEOUT_MS)
    try:
        if not response.ok:
            raise RuntimeError(f"HWP download failed (HTTP {response.status}, fileNo={file_no})")
        data = response.body()
    finally:
        response.dispose()
    if not data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        raise RuntimeError(f"Official download is not an HWP compound file (fileNo={file_no})")
    with TemporaryDirectory(prefix="knue-hwp-") as tmp:
        source = Path(tmp) / "source.hwp"
        source.write_bytes(data)
        try:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("hwp_fallback.py")), str(source)],
                capture_output=True, text=True, encoding="utf-8", check=True,
                timeout=HWP_CONVERT_TIMEOUT_SECONDS,
            )
            recovered = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise RuntimeError(f"HWP conversion failed (fileNo={file_no}): {exc}") from exc
    # Serve no converted assets or scripts; extraction uses the existing table logic.
    recovery_context = page.context.browser.new_context(java_script_enabled=False)
    recovery_page = recovery_context.new_page()
    try:
        recovery_page.route("**/*", lambda route: route.abort())
        recovery_page.set_content(recovered["html"], wait_until="domcontentloaded")
        if recovery_page.locator("body img, body object, body svg").count():
            raise RuntimeError("HWP contains unsupported visual content")
        body_text = recovery_page.locator("body").text_content() or ""
        _verify_hwp_text(recovered["paragraphs"], body_text)
        text = recovery_page.evaluate(
            f"(labels) => ({EXTRACT_BODY_JS})(document.body, labels)",
            CONFIRMED_WRAPPED_HEADERS.get(file_no, []),
        )
        # HWP character runs can contain doubled spaces inside ordinary prose.
        # Only DOM tables carry column structure; suppress the RAW spacing heuristic.
        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
        _verify_hwp_text(recovered["paragraphs"], convert_to_markdown(lines), markdown=True)
        return lines
    finally:
        recovery_context.close()


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
            try:
                _wait_for_completion(page)
            except PlaywrightTimeoutError:
                lines = _recover_hwp(page, file_no)
            else:
                lines = _extract_lines(page, file_no=file_no)
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
