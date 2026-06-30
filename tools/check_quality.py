"""Regulation quality gate: JSON integrity + markdown file checks.

Usage:
  python check_quality.py                    # full check (all files)
  python check_quality.py --files a.md b.md # check specific files only (PR mode)
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
REGULATIONS_JSON = ROOT / "tools" / "regulations.json"
REG_DIR = ROOT / "규정"

ERRORS: list[str] = []


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
    path_to_name: dict[Path, str] = {
        ROOT / r["local_path"]: r["name"]
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

    print()
    if ERRORS:
        print(f"❌ {len(ERRORS)}개 오류 발견")
        sys.exit(1)
    else:
        print("✅ 모든 검사 통과")


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
        if _check_md_file(path, reg["name"], root):
            fail_count += 1
    if fail_count == 0:
        ok(f"{len(regulations)}개 파일 품질 통과")


def _check_pr_files(
    files: list[str],
    path_to_name: dict[Path, str],
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
        name = path_to_name[path]
        if _check_md_file(path, name, root):
            fail_count += 1

    if fail_count == 0:
        ok("모든 변경 파일 품질 통과")


def _check_md_file(path: Path, name: str, root: Path) -> bool:
    """Returns True if any check failed."""
    rel = path.relative_to(root)
    text = path.read_text(encoding="utf-8")
    failed = False

    if not text.startswith(f"# {name}"):
        err(f"{rel}: 첫 줄이 '# {name}'으로 시작하지 않음")
        failed = True
    if len(text) < 500:
        err(f"{rel}: 파일 길이 {len(text)}자 (500자 미만)")
        failed = True
    if "\n## " not in text and not text.startswith("## "):
        err(f"{rel}: '## ' 헤더 없음")
        failed = True
    if "․" in text:
        count = text.count("․")
        err(f"{rel}: U+2024(ONE DOT LEADER) {count}개 — U+00B7(·)로 교체 필요")
        failed = True

    return failed


if __name__ == "__main__":
    main()
