"""Markdown quality gate checks."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_quality  # noqa: E402

NAME = "한국교원대학교 테스트 규정"
BODY = f"# {NAME}\n\n---\n\n## 제1조(목적)\n" + "이 규정은 시험용이다. " * 10 + "\n"


@pytest.fixture(autouse=True)
def _reset_errors():
    check_quality.ERRORS.clear()
    yield
    check_quality.ERRORS.clear()


def _check(tmp_path: Path, extra: str) -> bool:
    path = tmp_path / "규정.md"
    path.write_text(BODY + extra, encoding="utf-8")
    return check_quality._check_md_file(path, NAME, tmp_path)


def test_clean_file_passes(tmp_path):
    assert not _check(tmp_path, "면적은 25㎡로 한다.\n")


# Manually replaced blocks bypass reformat_regulation._normalize_chars().
@pytest.mark.parametrize("unit", ["m²", "m2", "cm2", "km²"])
def test_unnormalized_area_unit_fails(tmp_path, unit):
    assert _check(tmp_path, f"면적은 25{unit}로 한다.\n")
    assert any("면적 단위" in e for e in check_quality.ERRORS)
