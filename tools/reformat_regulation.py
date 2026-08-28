"""KNUE 규정 RAW 마크다운 → 저장소 양식 변환기.

parse_preview.py 출력물(RAW)을 저장소 양식으로 변환한다.
규칙 기반 처리이므로 파일 길이에 관계없이 잘리지 않는다.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 노이즈 패턴 — 조용히 제거
_NOISE_RE = re.compile(
    r"^(?:법제처|국가법령정보센터)$"
    r"|^-\s*\d+\s*/\s*\d+\s*-$"          # - N / M -
    r"|^\d{2,4}-\d{3,4}-\d{4}$"           # 전화번호
)

# 개정 이력 줄 패턴
_HISTORY_RE = re.compile(
    r"^(?:제정|개정|전부개정|일부개정)\s+\d{4}\."
    r"|^\[시행\s+\d{4}\."
)

# 장(章): "제N장 제목" 독립 줄
_CHAPTER_RE = re.compile(r"^(제\d+장)\s+(.+)$")

# 절(節): "제N절 제목" 독립 줄
_SECTION_RE = re.compile(r"^(제\d+절)\s+(.+)$")

# 조(條): 제N조(제목) 또는 제N조의M(제목) — 조의 M 사이 공백 허용
_ARTICLE_RE = re.compile(r"^(제\d+조(?:의\s*\d+)?)\(([^)]+)\)(.*)")

# 부칙·별표·별지 — 원문이 "부 칙" 처럼 사이 공백을 두는 경우가 있다
_APPENDIX_RE = re.compile(r"^(부\s*칙|별표\s*\d*|별지\s*제?\d*\s*서식?)\s*(.*)")


_TABLE_SEP_RE = re.compile(r"^\|[-| ]+\|$")


def _is_noise(line: str) -> bool:
    return bool(_NOISE_RE.match(line))


def _table_row_as_history(line: str) -> str | None:
    """파이프 테이블 행이 이력 줄이면 평문으로 변환, 아니면 None.

    parse_preview.py 가 날짜 내부 공백을 테이블 구분자로 오인할 때 발생.
    예: `| 제정 1987. | 5. 15.(규정 제44호) |` → `제정 1987. 5. 15.(규정 제44호)`
    """
    if not line.startswith("|"):
        return None
    if _TABLE_SEP_RE.match(line.replace(" ", "")):
        return None
    cells = [c.strip() for c in line.strip("|").split("|") if c.strip()]
    if not cells:
        return None
    text = re.sub(r"\s{2,}", " ", " ".join(cells))
    return text if _HISTORY_RE.match(text) else None


def reformat(raw: str, reg_name: str) -> str:
    lines = [ln.rstrip() for ln in raw.splitlines()]

    # 장(章) 존재 여부에 따라 조문 헤더 레벨 결정
    has_chapters = any(_CHAPTER_RE.match(ln.strip()) for ln in lines)
    art_level = "###" if has_chapters else "##"

    out: list[str] = []

    # 1단계: parse_preview.py 가 생성한 # <제목> 줄 스킵
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].startswith("# "):
        i += 1

    # 2단계: 공포·개정 이력 줄 수집 (본문 시작 전까지)
    history: list[str] = []
    while i < len(lines):
        ln = lines[i].strip()
        i += 1
        if not ln or ln == "---" or _is_noise(ln) or ln == reg_name:
            continue
        if _HISTORY_RE.match(ln) or ln.startswith("[시행"):
            history.append(ln)
            continue
        # parse_preview.py 가 이력 줄을 테이블로 변환한 경우 복원
        table_hist = _table_row_as_history(ln)
        if table_hist is not None:
            history.append(table_hist)
            continue
        # 테이블 구분자 행(---|---) 스킵 — 이력 테이블 내부
        if _TABLE_SEP_RE.match(ln.replace(" ", "")):
            continue
        # 본문 시작 — i 를 한 칸 되돌림
        i -= 1
        break

    # 헤더 작성
    out.append(f"# {reg_name}")
    out.append("")
    if history:
        for j, h in enumerate(history):
            # 마지막 이력 줄을 제외한 줄 끝에 두 칸 공백(Markdown hard break)
            out.append(h + ("  " if j < len(history) - 1 else ""))
        out.append("")
        out.append("---")
        out.append("")

    # 3단계: 본문 처리
    while i < len(lines):
        raw_ln = lines[i]
        ln = raw_ln.strip()
        i += 1

        if not ln:
            if out and out[-1] != "":
                out.append("")
            continue

        if _is_noise(ln) or ln == reg_name:
            continue

        if ln == "---":
            if not (out and out[-1] == "---"):
                out.append("---")
            continue

        # 이미 ## 로 시작하는 줄(parse_preview.py 가 변환한 것) → 그대로
        if ln.startswith("## ") or ln.startswith("### "):
            if out and out[-1] != "":
                out.append("")
            out.append(ln)
            out.append("")
            continue

        # 장(章)
        m = _CHAPTER_RE.match(ln)
        if m:
            _push_blank(out)
            out.append(f"## {m.group(1)} {m.group(2)}")
            out.append("")
            continue

        # 절(節) — 장과 같은 ## 레벨
        m = _SECTION_RE.match(ln)
        if m:
            _push_blank(out)
            out.append(f"## {m.group(1)} {m.group(2)}")
            out.append("")
            continue

        # 조(條)
        m = _ARTICLE_RE.match(ln)
        if m:
            art_id = m.group(1)
            art_title = m.group(2)
            art_body = m.group(3).strip()
            _push_blank(out)
            out.append(f"{art_level} {art_id}({art_title})")
            if art_body:
                out.append("")
                out.append(art_body)
            continue

        # 부칙·별표·별지
        m = _APPENDIX_RE.match(ln)
        if m:
            # 원문의 "부 칙" 표기를 헤더 이름으로 정규화한다
            name = re.sub(r"\s+", "", m.group(1))
            rest = m.group(2).strip()
            _push_blank(out)
            out.append(f"{art_level} {name}")
            if rest:
                out.append("")
                out.append(rest)
            continue

        # 일반 줄(항·호·표 포함) — 원본 그대로
        out.append(raw_ln)

    # 연속 빈 줄 정리
    result: list[str] = []
    prev_empty = False
    for line in out:
        if line == "":
            if not prev_empty:
                result.append(line)
            prev_empty = True
        else:
            result.append(line)
            prev_empty = False

    return "\n".join(result).rstrip() + "\n"


def _push_blank(out: list[str]) -> None:
    if out and out[-1] != "":
        out.append("")


def main() -> None:
    parser = argparse.ArgumentParser(description="KNUE 규정 RAW → 저장소 양식 변환")
    parser.add_argument("--raw", required=True, help="parse_preview.py 출력 파일 경로")
    parser.add_argument("--reg-name", required=True, help="규정명 (예: 한국교원대학교 학칙)")
    parser.add_argument("--out", help="출력 파일 경로 (생략 시 stdout)")
    args = parser.parse_args()

    raw_text = Path(args.raw).read_text(encoding="utf-8")
    result = reformat(raw_text, args.reg_name)

    if args.out:
        Path(args.out).write_text(result, encoding="utf-8")
        print("done")
    else:
        sys.stdout.write(result)


if __name__ == "__main__":
    main()
