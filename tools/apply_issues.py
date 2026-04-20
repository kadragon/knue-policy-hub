"""regulation-update 라벨의 열린 GitHub 이슈를 일괄 소비하여
규정 파일과 regulations.json 을 갱신하는 오케스트레이터.

유형:
- [규정 삭제] → 파일 삭제 + JSON 엔트리 제거
- [규정 변경] → 미리보기 파싱 + AI 재포맷 + 파일 덮어쓰기 + JSON file_no 갱신
- [신규 규정] → 파싱 + 재포맷 + 신규 파일 생성 + JSON 엔트리 추가 (section 은 런타임 입력 필요)

작업은 feature 브랜치 위에서 유형/건별 커밋으로 누적된다. PR 생성과 이슈 닫기는 수동.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from check_updates import REGULATIONS_PATH, load_regulations, save_regulations
from parse_preview import parse_preview
from reformat_with_ollama import reformat, validate

REPO_ROOT = Path(__file__).resolve().parent.parent
REGULATION_ROOT = REPO_ROOT / "규정"

IssueKind = Literal["change", "new", "delete"]


@dataclass
class IssueTask:
    number: int
    kind: IssueKind
    name: str
    body: str
    old_file_no: int | None = None
    new_file_no: int | None = None
    file_no: int | None = None
    section: str | None = None


@dataclass
class Outcome:
    issue: IssueTask
    status: Literal["done", "skipped", "failed"]
    detail: str
    file_path: Path | None = None


# --------- issue 수집 / 파싱 ---------

TITLE_PREFIX_TO_KIND: dict[str, IssueKind] = {
    "[규정 변경]": "change",
    "[신규 규정]": "new",
    "[규정 삭제]": "delete",
}


def _fetch_issues() -> list[dict]:
    result = subprocess.run(
        [
            "gh", "issue", "list",
            "--label", "regulation-update",
            "--state", "open",
            "--limit", "200",
            "--json", "number,title,body",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _extract_field(body: str, label: str) -> str | None:
    m = re.search(rf"\*\*{re.escape(label)}\*\*\s*:\s*(.+)", body)
    return m.group(1).strip() if m else None


def _parse_issue(raw: dict) -> IssueTask | None:
    title = raw["title"]
    body = raw.get("body") or ""
    kind: IssueKind | None = None
    name = ""
    for prefix, k in TITLE_PREFIX_TO_KIND.items():
        if title.startswith(prefix):
            kind = k
            name = title[len(prefix):].strip()
            break
    if kind is None:
        return None

    task = IssueTask(number=raw["number"], kind=kind, name=name, body=body)
    body_name = _extract_field(body, "규정명")
    if body_name:
        task.name = body_name

    if kind == "change":
        old = _extract_field(body, "이전 fileNo")
        new = _extract_field(body, "새 fileNo")
        section = _extract_field(body, "분류")
        task.old_file_no = int(old) if old else None
        task.new_file_no = int(new) if new else None
        task.section = section
    elif kind == "new":
        fno = _extract_field(body, "fileNo")
        task.file_no = int(fno) if fno else None
    elif kind == "delete":
        fno = _extract_field(body, "기존 fileNo")
        section = _extract_field(body, "분류")
        task.file_no = int(fno) if fno else None
        task.section = section
    return task


# --------- git helpers ---------

def _run(cmd: list[str], cwd: Path = REPO_ROOT, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def _ensure_branch(name: str) -> None:
    current = _run(["git", "branch", "--show-current"]).stdout.strip()
    if current == name:
        return
    existing = _run(["git", "branch", "--list", name]).stdout.strip()
    if existing:
        _run(["git", "switch", name])
    else:
        _run(["git", "switch", "-c", name])


def _working_tree_clean() -> bool:
    return _run(["git", "status", "--porcelain"]).stdout.strip() == ""


def _stage_and_commit(paths: list[Path], message: str) -> None:
    if not paths:
        return
    _run(["git", "add", "--", *(str(p) for p in paths)])
    status = _run(["git", "status", "--porcelain"]).stdout.strip()
    if not status:
        return
    _run(["git", "commit", "-m", message])


# --------- 핵심 작업 ---------

def _find_entry(regulations: list[dict], name: str, file_no: int | None) -> dict | None:
    if file_no is not None:
        for r in regulations:
            if r["file_no"] == file_no:
                return r
    for r in regulations:
        if r["name"] == name:
            return r
    return None


def _write_reformatted(name: str, file_no: int, dest: Path, dry_run: bool) -> tuple[Path | None, str]:
    if dry_run:
        return dest, f"(dry-run) 파싱/재포맷 생략 — 대상 경로: {dest.relative_to(REPO_ROOT)}"
    parsed = parse_preview(file_no)
    final = reformat(name, parsed.markdown)
    issues = validate(name, final)
    if issues:
        return None, "AI 출력 품질 미달: " + "; ".join(issues)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(final, encoding="utf-8")
    return dest, f"{len(final)}자 → {dest.relative_to(REPO_ROOT)}"


def _handle_delete(task: IssueTask, data: dict, dry_run: bool) -> Outcome:
    regulations: list[dict] = data["regulations"]
    entry = _find_entry(regulations, task.name, task.file_no)
    if entry is None:
        return Outcome(task, "skipped", f"regulations.json 에서 '{task.name}' 을 찾지 못함")
    local_path = entry.get("local_path")
    removed_path: Path | None = None
    if local_path:
        p = REPO_ROOT / local_path
        if p.exists():
            removed_path = p
            if not dry_run:
                p.unlink()
    if not dry_run:
        data["regulations"] = [r for r in regulations if r is not entry]
    return Outcome(task, "done", f"삭제: {entry['name']} (fileNo={entry['file_no']})", removed_path)


def _handle_change(task: IssueTask, data: dict, dry_run: bool) -> Outcome:
    if task.new_file_no is None:
        return Outcome(task, "failed", "이슈 본문에서 새 fileNo 를 찾지 못함")
    regulations: list[dict] = data["regulations"]
    entry = _find_entry(regulations, task.name, task.old_file_no)
    if entry is None:
        return Outcome(task, "skipped", f"regulations.json 에서 '{task.name}' 엔트리 없음 — check_updates 먼저 돌렸는지 확인")
    if not entry.get("local_path"):
        return Outcome(task, "failed", f"'{task.name}' 의 local_path 가 비어 있음")

    dest = REPO_ROOT / entry["local_path"]
    try:
        written, detail = _write_reformatted(task.name, task.new_file_no, dest, dry_run)
    except Exception as e:
        return Outcome(task, "failed", f"파싱/재포맷 오류: {e}")
    if written is None:
        return Outcome(task, "skipped", detail)
    if not dry_run:
        entry["file_no"] = task.new_file_no
    return Outcome(task, "done", detail, written)


def _handle_new(task: IssueTask, data: dict, dry_run: bool, section_resolver) -> Outcome:
    if task.file_no is None:
        return Outcome(task, "failed", "이슈 본문에서 fileNo 를 찾지 못함")
    section = section_resolver(task)
    if not section:
        return Outcome(task, "skipped", "section(편/장)이 지정되지 않음 — 런타임 질의 필요")

    safe_name = task.name.replace("/", "_")
    rel_path = Path("규정") / section / f"{safe_name}.md"
    dest = REPO_ROOT / rel_path
    if dest.exists():
        return Outcome(task, "skipped", f"대상 파일이 이미 존재: {rel_path}")
    try:
        written, detail = _write_reformatted(task.name, task.file_no, dest, dry_run)
    except Exception as e:
        return Outcome(task, "failed", f"파싱/재포맷 오류: {e}")
    if written is None:
        return Outcome(task, "skipped", detail)

    if not dry_run:
        data["regulations"].append({
            "name": task.name,
            "file_no": task.file_no,
            "section": section,
            "local_path": str(rel_path),
        })
    return Outcome(task, "done", detail, written)


# --------- 실행 ---------

def _interactive_section_resolver(task: IssueTask) -> str | None:
    sys.stderr.write(
        f"\n[신규 규정] '{task.name}' 의 편/장(section)을 입력하세요. 예: 제2편/제1장\n"
        f"  (빈 입력 시 스킵) > "
    )
    sys.stderr.flush()
    try:
        line = input().strip()
    except EOFError:
        return None
    return line or None


def run(dry_run: bool, branch: str, auto_section: dict[int, str] | None = None) -> int:
    if not _working_tree_clean() and not dry_run:
        print("ERROR: working tree 가 깨끗하지 않습니다. 커밋/스태시 후 재시도하세요.", file=sys.stderr)
        return 1

    if not dry_run:
        _ensure_branch(branch)

    raw_issues = _fetch_issues()
    tasks = [t for t in (_parse_issue(r) for r in raw_issues) if t is not None]
    tasks.sort(key=lambda t: (0 if t.kind == "delete" else 1 if t.kind == "change" else 2, t.number))

    data = load_regulations()

    def resolver(task: IssueTask) -> str | None:
        if auto_section and task.number in auto_section:
            return auto_section[task.number]
        return _interactive_section_resolver(task)

    outcomes: list[Outcome] = []
    for task in tasks:
        if task.kind == "delete":
            outcomes.append(_handle_delete(task, data, dry_run))
        elif task.kind == "change":
            outcomes.append(_handle_change(task, data, dry_run))
        elif task.kind == "new":
            outcomes.append(_handle_new(task, data, dry_run, resolver))

    # JSON 저장 + 커밋 (유형별)
    if not dry_run:
        save_regulations(data)
        json_path = REGULATIONS_PATH
        # delete commits
        for o in [o for o in outcomes if o.status == "done" and o.issue.kind == "delete"]:
            paths = [p for p in (o.file_path, json_path) if p]
            _stage_and_commit(paths, f"[FIX] 규정 삭제: {o.issue.name} (closes #{o.issue.number})")
        # change commits (파일별)
        for o in [o for o in outcomes if o.status == "done" and o.issue.kind == "change"]:
            paths = [p for p in (o.file_path, json_path) if p]
            _stage_and_commit(
                paths,
                f"[FIX] 규정 갱신: {o.issue.name} (fileNo {o.issue.old_file_no}→{o.issue.new_file_no}, closes #{o.issue.number})",
            )
        # new commits
        for o in [o for o in outcomes if o.status == "done" and o.issue.kind == "new"]:
            paths = [p for p in (o.file_path, json_path) if p]
            _stage_and_commit(
                paths,
                f"[FEAT] 신규 규정: {o.issue.name} (fileNo={o.issue.file_no}, closes #{o.issue.number})",
            )

    # 요약 출력
    print("\n=== 실행 요약 ===")
    for status in ("done", "skipped", "failed"):
        items = [o for o in outcomes if o.status == status]
        if not items:
            continue
        print(f"\n[{status}] {len(items)}건")
        for o in items:
            print(f"  #{o.issue.number} {o.issue.kind} {o.issue.name} — {o.detail}")

    failed = sum(1 for o in outcomes if o.status == "failed")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="regulation-update 이슈 일괄 처리")
    parser.add_argument("--dry-run", action="store_true", help="파일/JSON/git 변경 없이 계획만 출력")
    parser.add_argument(
        "--branch",
        default=f"regulation-sync/{datetime.now().strftime('%Y-%m-%d')}",
        help="작업 브랜치 이름",
    )
    parser.add_argument(
        "--section",
        action="append",
        default=[],
        metavar="ISSUE_NUM=SECTION",
        help="신규 규정 이슈의 section 을 비대화식으로 지정 (예: --section 23=제3편/제2장)",
    )
    args = parser.parse_args()

    auto_section: dict[int, str] = {}
    for spec in args.section:
        if "=" not in spec:
            print(f"ERROR: --section 형식 오류: {spec}", file=sys.stderr)
            sys.exit(2)
        k, v = spec.split("=", 1)
        auto_section[int(k)] = v.strip()

    sys.exit(run(dry_run=args.dry_run, branch=args.branch, auto_section=auto_section))


if __name__ == "__main__":
    main()
