"""Do not accept a viewer that stops loading halfway through a document."""

import sys
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
