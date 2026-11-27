"""Article-by-article comparison of two regulation Markdown versions."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import compare_articles  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
OLD = FIXTURES / "article_diff_old.md"
NEW = FIXTURES / "article_diff_new.md"


def _rows(page: str) -> list[str]:
    return re.findall(r'<tr class="(added|deleted|modified)">', page)


def _md(*articles: str, appendix: str = "") -> str:
    return "# 규정\n\n---\n\n" + "\n".join(articles) + appendix


def _compare(old: str, new: str, tmp_path: Path) -> str:
    (tmp_path / "old.md").write_text(old, encoding="utf-8")
    (tmp_path / "new.md").write_text(new, encoding="utf-8")
    return compare_articles.compare_files(tmp_path / "old.md", tmp_path / "new.md")


def test_fixture_pair_shows_only_modified_and_added():
    page = compare_articles.compare_files(OLD, NEW)
    assert _rows(page) == ["modified", "added"]
    assert "4년으로 한다" in page and "5년으로 한다" in page
    assert "제3조의2" in page and "복학하여야" in page


def test_unchanged_articles_and_appendix_are_not_listed():
    page = compare_articles.compare_files(OLD, NEW)
    for unchanged in ("시험용 조문 비교", "일반휴학", "총장이 따로 정한다"):
        assert unchanged not in page
    # 부칙 reuses 제1조/제2조 and its 제1조 text differs between the versions.
    assert "시행일" not in page and "경과조치" not in page
    assert "2024년 3월 1일" not in page
    assert "부칙·별표·별지는 비교 대상에서 제외" in page


def test_page_states_it_is_a_review_aid():
    page = compare_articles.compare_files(OLD, NEW)
    assert "공식 신구조문대비표를 대체하지 않습니다" in page


def test_article_with_branch_number_is_paired(tmp_path):
    old = _md("### 제3조(휴학)\n\n휴학한다.\n", "### 제3조의2(복학)\n\n복학한다.\n")
    new = _md("### 제3조(휴학)\n\n휴학한다.\n", "### 제3조의2(복학)\n\n복학하여야 한다.\n")
    page = _compare(old, new, tmp_path)
    assert _rows(page) == ["modified"]
    assert "제3조의2" in page


def test_spaced_branch_number_matches_compact_one(tmp_path):
    old = _md("### 제3조의 2(복학)\n\n복학한다.\n")
    new = _md("### 제3조의2(복학)\n\n복학한다.\n")
    assert _rows(_compare(old, new, tmp_path)) == []


def test_renumbered_article_is_delete_plus_add(tmp_path):
    old = _md("### 제5조(위임)\n\n총장이 정한다.\n")
    new = _md("### 제6조(위임)\n\n총장이 정한다.\n")
    assert _rows(_compare(old, new, tmp_path)) == ["deleted", "added"]


def test_deleted_article(tmp_path):
    old = _md("### 제1조(목적)\n\n목적이다.\n", "### 제2조(정의)\n\n정의한다.\n")
    new = _md("### 제1조(목적)\n\n목적이다.\n")
    page = _compare(old, new, tmp_path)
    assert _rows(page) == ["deleted"]
    row = re.findall(r'<tr class="deleted">.*?</tr>', page, re.S)[0]
    assert "(정의)" in row and row.endswith('<td class="text"></td></tr>')


def test_whitespace_only_difference_is_not_a_change(tmp_path):
    old = _md("### 제1조(목적)\n\n이 규정은   목적이다.  \n")
    new = _md("### 제1조(목적)\n\n\n이 규정은 목적이다.\n")
    assert _rows(_compare(old, new, tmp_path)) == []


def test_title_change_is_a_modification(tmp_path):
    old = _md("### 제1조(목적)\n\n같은 본문이다.\n")
    new = _md("### 제1조(취지)\n\n같은 본문이다.\n")
    assert _rows(_compare(old, new, tmp_path)) == ["modified"]


def test_articles_after_appendix_are_skipped_until_next_chapter(tmp_path):
    old = _md("### 제1조(목적)\n\n본문.\n", appendix="\n### 부칙\n\n#### 제9조(경과)\n\n옛 문구.\n")
    new = _md("### 제1조(목적)\n\n본문.\n", appendix="\n### 부칙\n\n#### 제9조(경과)\n\n새 문구.\n")
    assert _rows(_compare(old, new, tmp_path)) == []


def test_html_escapes_source_text(tmp_path):
    old = _md("### 제1조(목적)\n\n본문.\n")
    new = _md("### 제1조(목적)\n\n<script>alert(1)</script> & <b>굵게</b>\n")
    page = _compare(old, new, tmp_path)
    assert "<script>" not in page and "<b>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &lt;b&gt;" in page


def test_duplicate_number_is_reported_and_other_articles_still_compared(tmp_path):
    dup = ("### 제1조(목적)\n\n가.\n", "### 제1조(삭제)\n\n삭제\n")
    old = _md(*dup, "### 제2조(정의)\n\n옛 정의.\n")
    new = _md(*dup, "### 제2조(정의)\n\n새 정의.\n")
    page = _compare(old, new, tmp_path)
    assert _rows(page) == ["modified"]
    assert "번호가 중복되어 짝을 맞출 수 없는 조문은 비교하지 않았습니다: 제1조" in page


def test_unformatted_input_is_rejected():
    with pytest.raises(ValueError, match="no body articles found"):
        compare_articles.parse_articles("제1조(목적) 이 규정은...\n", "raw.md")


def test_malformed_number_is_not_truncated_to_the_article_before_it(tmp_path):
    old = _md("### 제10조(위원회)\n\n같다.\n", "### 제10조2(소위원회)\n\n소위원회 본문.\n")
    new = _md("### 제10조(위원회)\n\n같다.\n", "### 제10조의2(소위원회)\n\n소위원회 본문.\n")
    # The malformed heading is not an article, so it neither collides with 제10조
    # nor leaks into it: only the corrected 제10조의2 shows up, as an addition.
    assert _rows(_compare(old, new, tmp_path)) == ["added"]


def test_trailing_attachment_does_not_modify_last_article(tmp_path):
    old = _md("### 제1조(목적)\n\n본문.\n", appendix="\n## [붙임] 목록\n\n옛 표\n")
    new = _md("### 제1조(목적)\n\n본문.\n", appendix="\n## [붙임] 목록\n\n새 표\n")
    assert _rows(_compare(old, new, tmp_path)) == []


def test_deeper_subheading_stays_inside_its_article(tmp_path):
    old = _md("### 제1조(요금)\n\n#### 가. 기본\n\n1000원\n")
    new = _md("### 제1조(요금)\n\n#### 가. 기본\n\n2000원\n")
    assert _rows(_compare(old, new, tmp_path)) == ["modified"]


def test_cli_writes_utf8_html(tmp_path, capsys):
    out = tmp_path / "diff.html"
    assert compare_articles.main([str(OLD), str(NEW), "--out", str(out)]) == 0
    page = out.read_text(encoding="utf-8")
    assert _rows(page) == ["modified", "added"]
    assert capsys.readouterr().out == ""


def test_cli_missing_file_exits_nonzero(tmp_path, capsys):
    assert compare_articles.main([str(tmp_path / "nope.md"), str(NEW)]) == 1
    assert "error:" in capsys.readouterr().err


def test_cli_unformatted_input_exits_nonzero(tmp_path, capsys):
    raw = tmp_path / "raw.md"
    raw.write_text("제1조(목적) 이 규정은...\n", encoding="utf-8")
    assert compare_articles.main([str(raw), str(NEW)]) == 1
    assert "no body articles found" in capsys.readouterr().err


def test_cli_refuses_to_overwrite_an_input(tmp_path, capsys):
    new = tmp_path / "new.md"
    original = NEW.read_text(encoding="utf-8")
    new.write_text(original, encoding="utf-8")
    assert compare_articles.main([str(OLD), str(new), "--out", str(new)]) == 1
    assert new.read_text(encoding="utf-8") == original
    assert "refusing to overwrite" in capsys.readouterr().err


def test_cli_unwritable_out_exits_nonzero(tmp_path, capsys):
    out = tmp_path / "missing-dir" / "diff.html"
    assert compare_articles.main([str(OLD), str(NEW), "--out", str(out)]) == 1
    assert "error:" in capsys.readouterr().err
