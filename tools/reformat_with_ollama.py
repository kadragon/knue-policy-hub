"""중간 마크다운 → 저장소 양식의 최종 마크다운 (로컬 ollama 사용).

목표 양식: `규정/제1편/제1장/한국교원대학교 설치령.md` 류 파일.
  # {규정명}
  (공포 정보 한 줄)
  시행 YYYY. M. D.
  ## 제N조(제목)
  본문...
  ## 부칙 ...
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import ollama

MODEL = "gemma4:e4b"
MIN_OUTPUT_LEN = 500
REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_PATH = REPO_ROOT / "규정" / "제1편" / "제2장" / "한국교원대학교 대학원 학칙.md"
EXAMPLE_MAX_CHARS = 3500

SYSTEM_PROMPT = """\
너는 한국 법령/규정 문서 편집기다. 입력된 RAW 마크다운(KNUE 미리보기에서 기계 추출된 것)을
저장소 표준 양식으로 재정렬하라.

핵심 원칙: **입력 RAW 에 명시적으로 존재하는 텍스트만 사용**한다. 모양을 예시와 맞추기 위해
새 줄/새 헤더/새 이력을 만들어서는 안 된다. 불확실하면 생략한다.

엄격한 규칙:
1. 최상단: `# {규정명}` 을 정확히 한 번. 규정명은 사용자가 인자로 지정한 값을 그대로 사용.
2. 공포/개정 이력:
   - RAW 에 `[시행 ...] [... 제N호, YYYY. M. D., 일부개정]` 같은 단일 헤더 줄이 있으면 그대로 한 줄로 보존한다.
   - RAW 에 `제정 YYYY. M. D.` / `개정 YYYY. M. D.(제N호)` 같은 **독립된 줄**이 여러 개 나열되어 있을 때만
     각 줄을 그대로 옮기고, 마지막 줄을 제외한 줄 끝에 두 칸 공백(마크다운 hard break)을 붙인다.
   - **조문 본문 안의 `<개정 YYYY. M. D.>` 주석을 근거로 개정 이력 줄을 새로 만들지 마라.**
   - 이력/헤더 다음에는 빈 줄 → `---` → 빈 줄.
3. 장(章) 헤더:
   - RAW 에 `제N장 {제목}` 이라는 **독립 줄**이 실제로 존재할 때만 `## 제N장 {제목}` 을 생성한다.
   - 없으면 장 헤더를 넣지 마라. 이 경우 조문 헤더는 `## 제M조({조문제목})` 1단 구조로 한다.
   - 장이 있으면 조문 헤더는 `### 제M조({조문제목})` 2단 구조로 한다.
4. 조문:
   - RAW 의 `제N조(제목) 본문...` 혹은 `제N조의M(제목) 본문...` 패턴을 찾아 조문 헤더와 본문을 분리한다.
   - 조문 내부의 항(①②③... 또는 1. 2. 3.)과 호(가. 나. 다.) 표기, `<개정 YYYY. M. D.>` / `[본조신설 ...]` /
     `[제목개정 ...]` 주석은 원문 그대로 보존한다.
5. `부칙`, `별표`, `별지` 는 본문 섹션과 동일한 헤더 레벨로 유지. RAW 의 표(`| ... |`)는 그대로 둔다.
6. 파서 노이즈 제거 가능 항목(조용히 버려도 되는 것):
   - `법제처`, `국가법령정보센터`, `- N / M -`, 규정명이 본문 시작 전에 중복 반복된 줄, 전화번호 한 줄.
   그 외는 버리지 마라.
7. 출력은 오직 완성된 마크다운 전체. 설명/코드펜스/머릿말/후기 금지.
"""


def _read_example() -> str:
    try:
        text = EXAMPLE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    return text[:EXAMPLE_MAX_CHARS]


def _build_user_prompt(name: str, raw_markdown: str) -> str:
    example = _read_example()
    return (
        f"규정명: {name}\n\n"
        f"--- 목표 양식 예시 (다른 규정의 앞부분) ---\n{example}\n--- 예시 끝 ---\n\n"
        f"--- RAW 마크다운 ---\n{raw_markdown}\n--- RAW 끝 ---\n\n"
        "위 RAW 마크다운을 목표 양식으로 재정렬한 최종 마크다운만 출력하라."
    )


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def reformat(name: str, raw_markdown: str, model: str = MODEL) -> str:
    response = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(name, raw_markdown)},
        ],
        options={"temperature": 0.1},
        stream=False,
    )
    content = response["message"]["content"]
    return _strip_code_fence(content).rstrip() + "\n"


def validate(name: str, output: str) -> list[str]:
    """AI 출력 품질 점검. 문제를 문자열 리스트로 반환 (빈 리스트 = OK)."""
    issues: list[str] = []
    if len(output) < MIN_OUTPUT_LEN:
        issues.append(f"출력 길이가 {len(output)}자로 너무 짧음 (< {MIN_OUTPUT_LEN})")
    first_line = output.lstrip().splitlines()[0] if output.strip() else ""
    if not first_line.startswith("# "):
        issues.append(f"첫 줄이 H1이 아님: {first_line!r}")
    elif name not in first_line:
        issues.append(f"H1에 규정명이 포함되지 않음: {first_line!r}")
    if "## " not in output:
        issues.append("H2(조문) 헤더가 하나도 없음")
    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description="ollama로 RAW 마크다운을 저장소 양식으로 재정렬")
    parser.add_argument("--name", required=True, help="규정명 (H1에 사용)")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--input", type=Path, help="RAW 마크다운 파일 경로 (생략 시 stdin)")
    args = parser.parse_args()

    raw = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
    if not raw.strip():
        print("ERROR: 입력 RAW 마크다운이 비었습니다", file=sys.stderr)
        sys.exit(1)

    output = reformat(args.name, raw, model=args.model)
    issues = validate(args.name, output)
    if issues:
        print("WARN: 출력 품질 점검 이슈:", file=sys.stderr)
        for i in issues:
            print(f"  - {i}", file=sys.stderr)
    sys.stdout.write(output)
    sys.exit(2 if issues else 0)


if __name__ == "__main__":
    main()
