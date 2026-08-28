"""Regulation quality gate: JSON integrity + markdown file checks.

Usage:
  python check_quality.py                    # full check (all files)
  python check_quality.py --files a.md b.md # check specific files only (PR mode)
"""

import argparse
import json
import re
import sys
from pathlib import Path

from taxonomy import AUDIENCE_SET, AUDIENCES, DOMAIN_SET, DOMAINS

ROOT = Path(__file__).parent.parent
REGULATIONS_JSON = ROOT / "tools" / "regulations.json"
REG_DIR = ROOT / "규정"
AGENT_PROMPT = ROOT / "docs" / "rag-agent-prompt.md"

ERRORS: list[str] = []

# 본문에 남은 "규정 정식명" 줄. parse_preview.py 가 넘긴 원문 제목이
# regulations.json 의 이름과 다르면 엉뚱한 fileNo 를 파싱했다는 신호다.
_TITLE_LINE_RE = re.compile(
    r"^(한국교원대학교\s*\S.*?(?:규정|규칙|학칙|정관|행동강령|권리장전|설치령))$"
)


# 헤더로 승격되지 못하고 평문으로 남은 부칙 줄
_PLAIN_APPENDIX_RE = re.compile(r"^부\s*칙\s*(\(.*\))?\s*$", re.MULTILINE)


def _norm(name: str) -> str:
    return name.replace(" ", "")


def err(msg: str) -> None:
    ERRORS.append(msg)
    print(f"  FAIL  {msg}", flush=True)


def ok(msg: str) -> None:
    print(f"  ok    {msg}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--files",
        nargs="*",
        metavar="FILE",
        help="Check only these files (repo-relative paths). Skips JSON integrity check.",
    )
    parser.add_argument(
        "--files-from",
        metavar="PATH",
        help="Newline-separated file list (repo-relative). Skips JSON integrity check.",
    )
    args = parser.parse_args()
    file_list: list[str] | None = None
    if args.files_from:
        file_list = Path(args.files_from).read_text(encoding="utf-8").splitlines()
        file_list = [f for f in file_list if f.strip()]
    elif args.files is not None:
        file_list = args.files
    pr_mode = file_list is not None

    data = json.loads(REGULATIONS_JSON.read_text(encoding="utf-8"))
    regulations: list[dict] = data["regulations"]

    # name lookup by absolute path
    path_to_name: dict[Path, tuple[str, str | None]] = {
        ROOT / r["local_path"]: (r["name"], r.get("official_name"))
        for r in regulations
        if r.get("local_path")
    }
    registered_paths: set[Path] = set(path_to_name.keys())

    if not pr_mode:
        _check_json_integrity(regulations, registered_paths)
        _check_unregistered_files(registered_paths)
        _check_all_markdown(regulations, ROOT)
    else:
        _check_pr_files(file_list or [], path_to_name, registered_paths, ROOT)

    # 축 어휘 동기화는 규정 md 변경 여부와 무관하므로 두 모드 모두에서 검사한다
    _check_agent_prompt_axes()

    print()
    if ERRORS:
        print(f"❌ {len(ERRORS)}개 오류 발견")
        sys.exit(1)
    else:
        print("✅ 모든 검사 통과")


def _check_agent_prompt_axes() -> None:
    """docs/rag-agent-prompt.md 에 박힌 축 어휘 사본이 taxonomy.py 와 같은지 검사.

    프롬프트는 저장소 밖(운영 사이트)에 배포되므로 어휘를 인라인으로 싣는다.
    taxonomy.py 를 고치고 프롬프트를 잊으면 라우팅 지시와 메타 태그가 어긋난다.
    """
    print("\n[4] 에이전트 프롬프트 축 어휘 동기화")
    if not AGENT_PROMPT.exists():
        ok(f"{AGENT_PROMPT.name} 없음 — 건너뜀")
        return

    text = AGENT_PROMPT.read_text(encoding="utf-8")
    for heading, vocabulary, label in (
        ("# 축 1 — 업무영역", DOMAINS, "축 1(DOMAINS)"),
        ("# 축 2 — 적용대상", AUDIENCES, "축 2(AUDIENCES)"),
    ):
        if heading not in text:
            err(f"{AGENT_PROMPT.name}: '{heading}' 절을 찾을 수 없음")
            continue
        # 헤딩 다음의 첫 값 문단(" / " 구분) 만 읽는다
        listed: set[str] = set()
        for para in text.split(heading, 1)[1].split("\n\n"):
            para = para.strip()
            if para and not para.startswith("-") and "/" in para:
                listed = {v.strip() for v in para.replace("\n", " ").split("/") if v.strip()}
                break
        expected = set(vocabulary)
        missing = sorted(expected - listed)
        extra = sorted(listed - expected)
        if missing or extra:
            detail = []
            if missing:
                detail.append(f"누락 {missing}")
            if extra:
                detail.append(f"초과 {extra}")
            err(f"{AGENT_PROMPT.name} {label}: taxonomy.py 와 불일치 — {', '.join(detail)}")
        else:
            ok(f"{label} {len(expected)}개 일치")


def _check_json_integrity(
    regulations: list[dict], registered_paths: set[Path]
) -> None:
    print("\n[1] regulations.json integrity")
    seen_file_no: dict[int, str] = {}

    for reg in regulations:
        name: str = reg.get("name", "")
        file_no = reg.get("file_no")
        section: str = reg.get("section", "")
        local_path = reg.get("local_path")

        if not name:
            err(f"file_no={file_no}: name 누락")
        if file_no is None:
            err(f"name={name!r}: file_no 누락")
        if not section:
            err(f"name={name!r}: section 비어 있음 (미완성 엔트리)")
        _check_taxonomy(reg, name)

        if not local_path:
            err(f"name={name!r}: local_path null/비어 있음 (미완성 엔트리)")
            continue

        path = ROOT / local_path
        if isinstance(file_no, int):
            if file_no in seen_file_no:
                err(f"file_no={file_no} 중복: {seen_file_no[file_no]!r} vs {name!r}")
            else:
                seen_file_no[file_no] = name

        if not path.exists():
            err(f"{local_path}: 파일 없음 (JSON 등록됐으나 md 미생성)")

    ok(f"{len(regulations)}개 엔트리 검사 완료")


def _check_taxonomy(reg: dict, name: str) -> None:
    """domain/audience 2축 태그 검증 (tools/taxonomy.py 어휘 기준)."""
    domain = reg.get("domain")
    if not domain:
        err(f"name={name!r}: domain 누락 — tools/taxonomy.py DOMAINS 중 하나를 지정")
    elif domain not in DOMAIN_SET:
        err(f"name={name!r}: domain={domain!r} 은 정의되지 않은 값")

    audience = reg.get("audience")
    if not isinstance(audience, list) or not audience:
        err(f"name={name!r}: audience 누락 — tools/taxonomy.py AUDIENCES에서 1개 이상 지정")
        return
    for a in audience:
        if a not in AUDIENCE_SET:
            err(f"name={name!r}: audience={a!r} 은 정의되지 않은 값")


def _check_unregistered_files(registered_paths: set[Path]) -> None:
    print("\n[2] 미등록 마크다운 파일")
    all_md = set(REG_DIR.rglob("*.md"))
    unregistered = sorted(all_md - registered_paths)
    if unregistered:
        for p in unregistered:
            err(f"{p.relative_to(ROOT)}: regulations.json 미등록")
    else:
        ok(f"규정/*.md {len(all_md)}개 모두 등록됨")


def _check_all_markdown(regulations: list[dict], root: Path) -> None:
    print("\n[3] 마크다운 품질 게이트")
    fail_count = 0
    for reg in regulations:
        if not reg.get("local_path"):
            continue
        path = root / reg["local_path"]
        if not path.exists():
            continue
        if _check_md_file(path, reg["name"], root, reg.get("official_name")):
            fail_count += 1
    if fail_count == 0:
        ok(f"{len(regulations)}개 파일 품질 통과")


def _check_pr_files(
    files: list[str],
    path_to_name: dict[Path, tuple[str, str | None]],
    registered_paths: set[Path],
    root: Path,
) -> None:
    md_files = [root / f for f in files if f.endswith(".md") and f.startswith("규정/")]
    if not md_files:
        ok("검사할 규정 마크다운 파일 없음")
        return

    print(f"\n[PR] {len(md_files)}개 파일 검사")
    fail_count = 0
    for path in md_files:
        if not path.exists():
            continue  # deleted file — skip
        if path not in registered_paths:
            err(f"{path.relative_to(root)}: regulations.json 미등록")
            fail_count += 1
            continue
        name, official_name = path_to_name[path]
        if _check_md_file(path, name, root, official_name):
            fail_count += 1

    if fail_count == 0:
        ok("모든 변경 파일 품질 통과")


def _check_md_file(
    path: Path, name: str, root: Path, official_name: str | None = None
) -> bool:
    """Returns True if any check failed."""
    rel = path.relative_to(root)
    text = path.read_text(encoding="utf-8")
    failed = False

    if _check_body_title(rel, text, official_name or name):
        failed = True

    if not text.startswith(f"# {name}"):
        err(f"{rel}: 첫 줄이 '# {name}'으로 시작하지 않음")
        failed = True
    if len(text) < 100:
        err(f"{rel}: 파일 길이 {len(text)}자 (100자 미만)")
        failed = True
    if "\n## " not in text and not text.startswith("## "):
        err(f"{rel}: '## ' 헤더 없음")
        failed = True
    plain = _PLAIN_APPENDIX_RE.findall(text)
    if plain:
        err(
            f"{rel}: 부칙 {len(plain)}건이 헤더가 아닌 평문으로 남음 "
            "— reformat_regulation.py 로 재생성 필요"
        )
        failed = True
    if "․" in text:
        count = text.count("․")
        err(f"{rel}: U+2024(ONE DOT LEADER) {count}개 — U+00B7(·)로 교체 필요")
        failed = True

    return failed


def _check_body_title(rel: Path, text: str, expected: str) -> bool:
    """본문에 남은 규정 정식명이 기대 이름과 다른지 검사.

    첫 줄(`# <name>`)은 스킬이 직접 써 넣으므로 오파싱을 잡지 못한다.
    파서가 원문에서 넘긴 제목 줄이 실제 문서의 신원이다.
    """
    want = _norm(expected)
    for i, line in enumerate(text.split("\n")[1:], start=2):
        found = line.strip()
        if not _TITLE_LINE_RE.match(found):
            continue
        got = _norm(found)
        if got == want or got in want or want in got:
            continue
        err(
            f"{rel}:{i}: 본문 규정명 {found!r} 이 {expected!r} 과 불일치 "
            "— 다른 fileNo 를 파싱했거나 regulations.json 의 name 이 틀렸을 수 있음 "
            "(정식명이 목록명과 다른 규정은 official_name 필드로 명시)"
        )
        return True
    return False


if __name__ == "__main__":
    main()
