"""Do not accept a viewer that stops loading halfway through a document."""

import sys
from contextlib import nullcontext
from types import SimpleNamespace
from pathlib import Path

import pytest
from playwright.sync_api import TimeoutError, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import parse_preview  # noqa: E402


@pytest.fixture
def page():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        yield page
        browser.close()


def test_stalled_partial_viewer_fails(page, monkeypatch):
    monkeypatch.setattr(parse_preview, "CONTENT_LOAD_TIMEOUT_MS", 100)
    page.set_content('''<iframe id="innerWrap" srcdoc="<div id=content_body>First page</div>"></iframe>''')
    with pytest.raises(TimeoutError):
        parse_preview._wait_for_completion(page)


def test_delayed_last_page_is_included(page):
    page.set_content('''<iframe id="innerWrap" srcdoc="<div id=content_body>First page</div>"></iframe>''')
    page.evaluate('''() => {
        const frame = document.querySelector('iframe').contentWindow;
        frame.localSynap = {completed: 0};
        setTimeout(() => {
            frame.document.querySelector('#content_body').append(' Last page');
            frame.localSynap.completed = 1;
        }, 200);
    }''')
    parse_preview._wait_for_completion(page)
    assert parse_preview._extract_lines(page) == ["First page Last page"]


@pytest.mark.parametrize("file_no,expected", [
    (1693, "입학인재관리과"),
    (1590, "입학인재 / 관리과"),
    (None, "입학인재 / 관리과"),
])
def test_confirmed_labels_are_document_scoped(page, file_no, expected):
    page.set_content('''<iframe id="innerWrap" srcdoc="<div id=content_body>
    <table><tr><td><p>입학인재</p><p>관리과</p></td><td>구 분</td></tr>
    <tr><td>가</td><td>나</td></tr></table></div>"></iframe>''')
    lines = parse_preview._extract_lines(page, file_no=file_no)
    assert f"| {expected} | 구 분 |" in lines


@pytest.fixture
def parser_page(page, monkeypatch):
    browser = SimpleNamespace(new_page=lambda: page, close=lambda: None)
    pw = SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kw: browser))
    monkeypatch.setattr(parse_preview, "sync_playwright", lambda: nullcontext(pw))
    return page


def test_incomplete_preview_uses_official_hwp(parser_page, monkeypatch):
    page = parser_page
    monkeypatch.setattr(parse_preview, "CONTENT_LOAD_TIMEOUT_MS", 100)
    monkeypatch.setattr(parse_preview, "POST_LOAD_WAIT_MS", 0)
    monkeypatch.setattr(type(page), "goto", lambda self, *a, **kw: self.set_content(
        '<iframe id="innerWrap" srcdoc="<div id=content_body>Partial</div>"></iframe>'
    ))
    calls = []

    def recover(recovery_page, file_no):
        calls.append(file_no)
        return ["Official title", "Last article"]

    monkeypatch.setattr(parse_preview, "_recover_hwp", recover, raising=False)
    result = parse_preview.parse_preview(1598)
    assert result.markdown == "Official title\nLast article\n"
    assert calls == [1598]


def test_complete_preview_does_not_download_hwp(parser_page, monkeypatch):
    page = parser_page
    monkeypatch.setattr(parse_preview, "POST_LOAD_WAIT_MS", 0)

    def navigate(self, *a, **kw):
        self.set_content('<iframe id="innerWrap" srcdoc="<div id=content_body>Complete</div>"></iframe>')
        self.evaluate("() => document.querySelector('iframe').contentWindow.localSynap = {completed: 1}")

    monkeypatch.setattr(type(page), "goto", navigate)
    monkeypatch.setattr(parse_preview, "_recover_hwp", lambda *a: pytest.fail("Unexpected download"), raising=False)
    assert parse_preview.parse_preview(1).markdown == "Complete\n"


def test_failed_recovery_never_returns_partial_preview(parser_page, monkeypatch):
    page = parser_page
    monkeypatch.setattr(parse_preview, "POST_LOAD_WAIT_MS", 0)
    monkeypatch.setattr(parse_preview, "CONTENT_LOAD_TIMEOUT_MS", 100)
    monkeypatch.setattr(type(page), "goto", lambda self, *a, **kw: self.set_content(
        '<iframe id="innerWrap" srcdoc="<div id=content_body>Partial</div>"></iframe>'
    ))

    def fail(*a):
        raise RuntimeError("HWP recovery failed")

    monkeypatch.setattr(parse_preview, "_recover_hwp", fail, raising=False)
    with pytest.raises(RuntimeError, match="HWP recovery failed"):
        parse_preview.parse_preview(1)


def test_hwp_source_text_loss_is_rejected():
    with pytest.raises(RuntimeError, match="missing"):
        parse_preview._verify_hwp_text(["First", "Last"], "First")


@pytest.fixture
def hwp_download(page, monkeypatch):
    import json

    state = {
        "data": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1fake",
        "status": 200,
        "html": "<html><body><p>Official title</p><table><tr><td>Header</td></tr>"
                "<tr><td>Final cell</td></tr></table><p>Last article</p></body></html>",
        "paragraphs": ["Official title", "Header", "Final cell", "Last article"],
        "disposed": False,
        "urls": [],
    }

    def get(self, url, **kw):
        state["urls"].append(url)
        return SimpleNamespace(
            ok=state["status"] == 200, status=state["status"], body=lambda: state["data"],
            dispose=lambda: state.update(disposed=True),
        )

    def convert(*a, **kw):
        return SimpleNamespace(stdout=json.dumps({"html": state["html"], "paragraphs": state["paragraphs"]}))

    monkeypatch.setattr(type(page.request), "get", get)
    monkeypatch.setattr(parse_preview.subprocess, "run", convert)
    return state


def test_hwp_recovery_preserves_final_table_and_article(page, hwp_download):
    lines = parse_preview._recover_hwp(page, 1598)
    assert "| Final cell |" in lines
    assert lines[-1] == "Last article"
    assert hwp_download["urls"] == [parse_preview.DOWNLOAD_URL.format(file_no=1598)]
    assert hwp_download["disposed"]
    assert len(page.context.pages) == 1


@pytest.mark.parametrize("failure", ["http", "not_hwp", "conversion", "html_loss", "markdown_loss", "image"])
def test_unrecoverable_hwp_is_rejected(page, hwp_download, monkeypatch, failure):
    if failure == "http":
        hwp_download["status"] = 404
    elif failure == "not_hwp":
        hwp_download["data"] = b"<html>Download error</html>"
    elif failure == "conversion":
        def fail(*a, **kw):
            raise parse_preview.subprocess.TimeoutExpired("converter", 120)
        monkeypatch.setattr(parse_preview.subprocess, "run", fail)
    elif failure == "html_loss":
        hwp_download["paragraphs"].append("Missing appendix")
    elif failure == "markdown_loss":
        hwp_download["html"] = hwp_download["html"].replace(
            "Last article", "<script>Last article</script>"
        )
    else:
        hwp_download["html"] = hwp_download["html"].replace("</body>", "<img src='missing.png'></body>")
    with pytest.raises(RuntimeError):
        parse_preview._recover_hwp(page, 1598)
    assert hwp_download["disposed"]
    assert len(page.context.pages) == 1


def test_repeated_source_cell_loss_is_rejected():
    with pytest.raises(RuntimeError, match="missing"):
        parse_preview._verify_hwp_text(["Same cell", "Same cell"], "Same cell")


def test_converter_rejects_invalid_compound_file(tmp_path):
    from hwp_fallback import convert
    source = tmp_path / "corrupt.hwp"
    source.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1broken")
    with pytest.raises(Exception):
        convert(source)


def test_hwp_prose_spacing_does_not_invent_tables(page, hwp_download):
    hwp_download["html"] = "<body><p>First sentence  revision.</p><p>Last sentence  revision.</p></body>"
    hwp_download["paragraphs"] = ["First sentence  revision.", "Last sentence  revision."]
    lines = parse_preview._recover_hwp(page, 1598)
    assert parse_preview.convert_to_markdown(lines) == "First sentence revision.\nLast sentence revision.\n"


def test_missing_short_paragraphs_cannot_reuse_long_paragraph_text():
    with pytest.raises(RuntimeError, match="missing"):
        parse_preview._verify_hwp_text(["성명", "성명", "성명 : 성명"], "성명 : 성명")


def test_hwp_table_bullets_keep_their_source_form(page, hwp_download):
    hwp_download["html"] = "<body><table><tr><td>□ 신청</td></tr><tr><td>완료</td></tr></table></body>"
    hwp_download["paragraphs"] = ["□ 신청", "완료"]
    assert "| □ 신청 |" in parse_preview._recover_hwp(page, 1598)


def test_repeated_numeric_paragraphs_preserve_boundaries():
    parse_preview._verify_hwp_text(["121", "212", "121"], "121\n212\n121")


def test_html_numeric_paragraphs_preserve_boundaries(page, hwp_download):
    hwp_download["html"] = "<body><p>121</p><p>212</p><p>121</p></body>"
    hwp_download["paragraphs"] = ["121", "212", "121"]
    assert parse_preview._recover_hwp(page, 1598) == ["121", "212", "121"]


def test_adjacent_paragraphs_cannot_prove_a_missing_combined_paragraph():
    with pytest.raises(RuntimeError, match="missing"):
        parse_preview._verify_hwp_text(["121212"], "121\n212")


def test_hwp_explicit_line_breaks_preserve_source_units(page, hwp_download):
    hwp_download["html"] = "<body><p>First clause\nSecond clause</p></body>"
    hwp_download["paragraphs"] = ["First clause", "Second clause"]
    assert parse_preview._recover_hwp(page, 1598) == ["First clause", "Second clause"]
