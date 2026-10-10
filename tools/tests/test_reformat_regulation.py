"""Source identity and table preservation at the RAW-to-Markdown boundary."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reformat_regulation import reformat  # noqa: E402

NAME = "한국교원대학교 자체행정감사 규정"


def test_title_spacing_keeps_history_and_discards_repeated_title():
    title = NAME.replace(" ", "")
    result = reformat(f"{title}\n제정 2020. 1. 1.\n{title}\n제1조(목적) 시험\n", NAME)
    assert "제정 2020. 1. 1.\n\n---" in result
    assert result.count(title) == 0
    assert "## 제1조(목적)" in result


@pytest.mark.parametrize("title", ["다른 규정", "", "제1조(목적) 시험"])
def test_wrong_or_missing_source_title_fails(title):
    with pytest.raises(ValueError, match="Source title mismatch"):
        reformat(title, NAME)


def test_official_title_is_validated_and_preserved():
    official = "한국교원대학교 정보전산원 규정"
    result = reformat(f"{official}\n제정 2001. 9. 1.\n제1조(목적) 시험", "한국교원대학교 교육정보원 규정", official)
    assert result.startswith("# 한국교원대학교 교육정보원 규정\n\n" + official)
    with pytest.raises(ValueError):
        reformat("한국교원대학교 다른 규정\n제1조(목적) 시험", NAME, official)


def test_appendix_table_passes_through_with_normalized_units():
    table = "| 이름 | 면적 |\n|---|---|\n| 가 | 25m² |"
    result = reformat(f"{NAME}\n제정 2020. 1. 1.\n제1조(목적) 시험\n[별지 제1호 서식]\n{table}\n", NAME)
    assert "## 별지 제1호 서식" in result
    assert table.replace("m²", "㎡") in result


def test_numbered_appendix_suffix_is_not_split_into_a_wrong_heading():
    result = reformat(f"{NAME}\n제1조(목적) 시험\n[별지 제2의2호] 삭제\n", NAME)
    assert "## 별지 제2의2호\n\n삭제" in result
    assert "\n의2호" not in result


def test_history_labeled_as_change_is_preserved():
    result = reformat(f"# {NAME}\n변경 1987. 12. 21.\n제1조(목적) 시험\n", NAME)
    assert "변경 1987. 12. 21.\n\n---" in result
