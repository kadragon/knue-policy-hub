"""extract_body.js 표 추출 로직 검증.

실제 사이트 대신 로컬 HTML fixture 를 chromium 에 올려 같은 JS 를 돌린다. fixture 는 KNUE
미리보기(HWP 내보내기) 형태를 따른다 — TH 없이 TD 만 쓰고, 셀 안 줄바꿈은 블록/<br> 로 온다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parse_preview import EXTRACT_BODY_JS  # noqa: E402

TBL_RE = re.compile(r"<<<TBL>>>\n(.*?)\n<<</TBL>>>", re.S)


@pytest.fixture(scope="module")
def extract():
    """(html) -> extract_body.js 결과 문자열."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()

        def run(html: str) -> str:
            page.set_content(html)
            return page.evaluate(
                f"""() => {{
                    const extractBody = {EXTRACT_BODY_JS};
                    return extractBody(document.body);
                }}"""
            )

        yield run
        browser.close()


def table_lines(text: str) -> list[str]:
    m = TBL_RE.search(text)
    assert m, f"표 sentinel 없음: {text!r}"
    return m.group(1).splitlines()


CASES = [
    pytest.param(
        # 조직 설치 규정 형태: 가로 스팬이 덮은 열은 원점에서 한 번만 찍는다.
        """<table>
          <tr><td colspan="3">조 직</td><td>직 위</td></tr>
          <tr><td colspan="3">교수부</td><td>부장</td></tr>
          <tr><td></td><td colspan="2">교수지원과</td><td>과장</td></tr>
        </table>""",
        [
            "| 조 직 |  |  | 직 위 |",
            "|---|---|---|---|",
            "| 교수부 |  |  | 부장 |",
            "|  | 교수지원과 |  | 과장 |",
        ],
        id="colspan-origin-only",
    ),
    pytest.param(
        # 세로 스팬은 행을 self-contained 하게 두기 위해 반복을 유지한다.
        """<table>
          <tr><td>구분</td><td>값</td></tr>
          <tr><td rowspan="2">가</td><td>1</td></tr>
          <tr><td>2</td></tr>
        </table>""",
        ["| 구분 | 값 |", "|---|---|", "| 가 | 1 |", "| 가 | 2 |"],
        id="rowspan-repeat-kept",
    ),
    pytest.param(
        # 한 셀에 쌓인 값은 textContent 로는 붙어버리므로 ' / ' 로 나눈다.
        """<table>
          <tr><td>등급</td><td>점수</td></tr>
          <tr><td>A</td><td><p>4.50</p><p>4.40-4.49</p></td></tr>
        </table>""",
        ["| 등급 | 점수 |", "|---|---|", "| A | 4.50 / 4.40-4.49 |"],
        id="stacked-values-separated",
    ),
    pytest.param(
        # 단일 문자 런은 세로쓰기이므로 구분자 없이 붙인다.
        """<table>
          <tr><td><p>계</p><p>급</p><p>별</p></td><td>수당</td></tr>
          <tr><td>1호</td><td>100</td></tr>
        </table>""",
        ["| 계급별 | 수당 |", "|---|---|", "| 1호 | 100 |"],
        id="vertical-label-merged",
    ),
    pytest.param(
        # 원문이 이미 쓴 슬래시는 겹치지 않는다.
        """<table>
          <tr><td><p>학술지</p><p>/출판사</p></td><td>비고</td></tr>
          <tr><td>가</td><td>나</td></tr>
        </table>""",
        ["| 학술지/출판사 | 비고 |", "|---|---|", "| 가 | 나 |"],
        id="literal-slash-not-doubled",
    ),
    pytest.param(
        # 서식의 빈 기입란 스무 줄은 빈 행 한 줄로 축약한다.
        """<table>
          <tr><td>성명</td><td>서명</td></tr>
          <tr><td></td><td></td></tr>
          <tr><td></td><td></td></tr>
          <tr><td></td><td></td></tr>
        </table>""",
        ["| 성명 | 서명 |", "|---|---|", "|  |  |"],
        id="blank-form-rows-collapsed",
    ),
    pytest.param(
        # 그룹 헤더 밴드는 한 행으로 접고, 그룹 라벨은 자식 열마다 남긴다.
        """<table>
          <tr><td rowspan="2">계 급</td><td colspan="3">하사관</td></tr>
          <tr><td>상사</td><td>중사</td><td>하사</td></tr>
          <tr><td>수당</td><td>1</td><td>2</td><td>3</td></tr>
        </table>""",
        [
            "| 계 급 | 하사관 / 상사 | 하사관 / 중사 | 하사관 / 하사 |",
            "|---|---|---|---|",
            "| 수당 | 1 | 2 | 3 |",
        ],
        id="header-band-folded",
    ),
    pytest.param(
        # 셀 안 파이프는 표 구조를 깨지 않도록 이스케이프한다.
        """<table>
          <tr><td>구분</td><td>값</td></tr>
          <tr><td>가|나</td><td>다</td></tr>
        </table>""",
        ["| 구분 | 값 |", "|---|---|", r"| 가\|나 | 다 |"],
        id="pipe-escaped",
    ),
]


@pytest.mark.parametrize("html,expected", CASES)
def test_table_markdown(extract, html: str, expected: list[str]):
    assert table_lines(extract(html)) == expected
