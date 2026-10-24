"""Exercise the weekly update CLI with local files and an in-memory HTTP server."""

import json
import sys
from datetime import datetime
from html import escape
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_updates  # noqa: E402


@pytest.fixture
def cli(tmp_path, monkeypatch):
    source_url = "https://regulations.invalid/list"
    records = [
        {"name": f"규정 {number}", "file_no": number, "section": "제1편/제1장",
         "domain": "학사·교육과정", "audience": ["학부생"],
         "local_path": f"규정/규정 {number}.md"}
        for number in range(1, check_updates.MIN_EXPECTED_REGULATIONS + 1)
    ]
    data = {"source_url": source_url, "last_checked": "2026-01-01T00:00:00Z",
            "regulations": records}
    path = tmp_path / "regulations.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(check_updates, "REGULATIONS_PATH", path)
    state = {"web": {r["file_no"]: r["name"] for r in records}, "status": 200}

    def respond(request):
        assert str(request.url) == source_url
        if state.get("timeout"):
            raise httpx.ReadTimeout("Simulated timeout", request=request)
        links = ['<a href="/other">Ignore</a>', '<a href="?fileNo=9999">Untitled</a>']
        for number, name in state["web"].items():
            for suffix in ("미리보기", "다운로드"):
                links.append(f'<a href="?fileNo={number}" '
                             f'title="{escape(name)} {suffix}[새창]">Open</a>')
        return httpx.Response(state["status"], text="\n".join(links))

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        # Keep real response parsing and HTTP status handling; replace only transport.
        monkeypatch.setattr(check_updates.httpx, "get", client.get)

        def run(*args):
            monkeypatch.setattr(sys, "argv", ["check_updates.py", *args])
            check_updates.main()

        yield path, data, state, run


def test_json_report_parses_links_without_writing(cli, capsys):
    path, data, state, run = cli
    before = path.read_bytes()
    del state["web"][1]
    state["web"][101] = "규정 1"
    run("--json")
    report = json.loads(capsys.readouterr().out)
    assert report["web_count"] == len(data["regulations"])
    assert report["stored_count"] == len(data["regulations"])
    assert report["changed"] == [{"name": "규정 1", "old_file_no": 1,
                                  "new_file_no": 101, "section": "제1편/제1장",
                                  "local_path": "규정/규정 1.md"}]
    assert report["new"] == report["removed"] == []
    assert path.read_bytes() == before


def test_update_persists_changes_and_preserves_metadata(cli):
    path, data, state, run = cli
    del state["web"][1]
    del state["web"][2]
    state["web"].update({101: "규정 1", 102: "신규 규정"})
    run("--update")
    saved = json.loads(path.read_text(encoding="utf-8"))
    by_number = {r["file_no"]: r for r in saved["regulations"]}
    assert by_number[101] == {**data["regulations"][0], "file_no": 101}
    assert 1 not in by_number and 2 not in by_number
    assert by_number[102] == {"name": "신규 규정", "file_no": 102,
                             "section": "", "domain": "", "audience": [], "local_path": None}
    assert [r for r in saved["regulations"] if r["file_no"] < 100] == data["regulations"][2:]
    assert saved["source_url"] == data["source_url"]
    assert saved["last_checked"] != data["last_checked"]
    assert datetime.strptime(saved["last_checked"], "%Y-%m-%dT%H:%M:%SZ")


def test_no_changes_leaves_index_byte_identical(cli):
    path, _, _, run = cli
    before = path.read_bytes()
    run("--update")
    assert path.read_bytes() == before


@pytest.mark.parametrize("count", [0, check_updates.MIN_EXPECTED_REGULATIONS - 1])
def test_incomplete_list_fails_without_output_or_index_write(cli, capsys, count):
    path, _, state, run = cli
    before = path.read_bytes()
    state["web"] = dict(list(state["web"].items())[:count])
    with pytest.raises(SystemExit) as error:
        run("--json", "--update")
    assert error.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "너무 적습니다" in captured.err
    assert path.read_bytes() == before


@pytest.mark.parametrize("failure", ["http", "timeout"])
def test_network_failure_cannot_modify_index(cli, capsys, failure):
    path, _, state, run = cli
    before = path.read_bytes()
    state["status"] = 503 if failure == "http" else 200
    state["timeout"] = failure == "timeout"
    with pytest.raises(httpx.HTTPStatusError if failure == "http" else httpx.ReadTimeout):
        run("--json", "--update")
    assert capsys.readouterr().out == ""
    assert path.read_bytes() == before


def test_duplicate_titles_warn_on_stderr_and_do_not_replace_local_entry(cli, capsys):
    path, _, state, run = cli
    before = path.read_bytes()
    del state["web"][1]
    state["web"].update({101: "규정 1", 102: "규정 1"})
    run("--json")
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["duplicate_titles"] == {"규정 1": [101, 102]}
    assert report["changed"] == report["new"] == report["removed"] == []
    assert "중복 노출" in captured.err
    run("--update")
    assert path.read_bytes() == before
