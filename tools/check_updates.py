"""KNUE 규정 fileNo 변경 감지 도구.

웹사이트에서 규정 목록을 스크래핑하여 저장된 fileNo와 비교합니다.
--check-revisions 로 fileNo 가 그대로인 채 본문만 개정된 규정도 감지합니다.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).parent.parent
REGULATIONS_PATH = Path(__file__).parent / "regulations.json"
MIN_EXPECTED_REGULATIONS = 85
DEFAULT_REVISION_WORKERS = 4
REVISION_PARSE_ATTEMPTS = 2

# "2026. 2. 27." 형태의 날짜. 제정/개정 이력, 조문 내 <개정 …>, 부칙 모두에 쓰인다.
DATE_RE = re.compile(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.")


def load_regulations() -> dict:
    with open(REGULATIONS_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_regulations(data: dict) -> None:
    with open(REGULATIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def fetch_web_regulations(source_url: str) -> dict[int, str]:
    """웹사이트에서 fileNo → 규정명 매핑을 스크래핑합니다."""
    response = httpx.get(source_url, timeout=30, follow_redirects=True)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    results: dict[int, str] = {}

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        match = re.search(r"fileNo=(\d+)", href)
        if not match:
            continue

        file_no = int(match.group(1))
        if file_no in results:
            continue

        # 규정명은 title 속성에서 추출 (예: "한국교원대학교 설치령 미리보기[새창]")
        title = a_tag.get("title", "")
        name = re.sub(r"\s*(미리보기|다운로드)\[새창\]$", "", title).strip()

        if name:
            results[file_no] = name

    return results


def warn_duplicate_titles(web: dict[int, str]) -> dict[str, list[int]]:
    """같은 이름으로 노출된 fileNo 를 경고한다.

    웹 목록의 `title` 속성이 앞 항목 이름으로 잘못 붙는 사례가 있다(예: fileNo
    1596 은 실제로는 「교수회 규정」이지만 title 은 「교수회평의회 규정」).
    이름만 믿고 신규 등록하면 기존 규정 파일을 덮어쓰게 되므로, 중복 이름은
    미리보기 본문으로 실제 규정명을 확인해야 한다.
    """
    by_name: dict[str, list[int]] = collections.defaultdict(list)
    for fno, name in web.items():
        by_name[name].append(fno)

    dups = {n: sorted(f) for n, f in by_name.items() if len(f) > 1}
    for name, fnos in sorted(dups.items()):
        print(
            f"경고: '{name}' 이 fileNo {fnos} 로 중복 노출됨 — "
            "웹 목록 title 오류 가능. parse_preview.py 로 실제 규정명 확인 필요.",
            file=sys.stderr,
        )
    return dups


def compare(
    stored: list[dict], web: dict[int, str]
) -> tuple[list[dict], list[dict], list[dict]]:
    """저장된 데이터와 웹 데이터를 비교합니다.

    Returns:
        (changed, new, removed) 튜플
        - changed: fileNo가 변경된 규정 (이름 기준 매칭)
        - new: 웹에만 존재하는 규정 (새로 추가된 fileNo)
        - removed: 저장소에만 존재하는 규정 (웹에서 삭제됨)
    """
    stored_by_file_no: dict[int, dict] = {r["file_no"]: r for r in stored}
    stored_file_nos = set(stored_by_file_no.keys())
    web_file_nos = set(web.keys())

    # 웹에 새로 나타난 fileNo
    new_file_nos = web_file_nos - stored_file_nos
    # 웹에서 사라진 fileNo
    removed_file_nos = stored_file_nos - web_file_nos

    # 이름 기준으로 변경 감지: 저장된 이름이 새 fileNo에 매핑되었는지 확인
    web_by_name: dict[str, int] = {name: fno for fno, name in web.items()}
    changed: list[dict] = []
    actually_new: list[dict] = []
    actually_removed: list[dict] = []

    # 사라진 fileNo의 규정 중, 웹에 같은 이름이 존재하는 경우 → 변경으로 처리
    matched_new_file_nos: set[int] = set()
    for fno in removed_file_nos:
        reg = stored_by_file_no[fno]
        name = reg["name"]
        if name in web_by_name:
            new_fno = web_by_name[name]
            changed.append({
                "name": name,
                "old_file_no": fno,
                "new_file_no": new_fno,
                "section": reg["section"],
                "local_path": reg["local_path"],
            })
            if new_fno in new_file_nos:
                matched_new_file_nos.add(new_fno)
        else:
            actually_removed.append({
                "name": name,
                "file_no": fno,
                "section": reg["section"],
            })

    # 매칭되지 않은 새 fileNo → 진짜 새 규정
    for fno in new_file_nos - matched_new_file_nos:
        actually_new.append({
            "name": web[fno],
            "file_no": fno,
        })

    return changed, actually_new, actually_removed


def latest_date(text: str) -> str | None:
    """문서 전체에서 가장 늦은 날짜를 ISO(YYYY-MM-DD) 로 돌려준다.

    개정 이력이 표로 조판되거나(파싱 시 헤더가 표 행으로 남는다) 헤더에 아예
    없고 부칙에만 있는 규정이 있어, 헤더만 보면 최신 개정을 놓친다. 문서 전체
    최대 날짜는 그런 조판 차이에 영향받지 않는다.
    """
    best: str | None = None
    for m in DATE_RE.finditer(text):
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1980 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
            continue
        iso = f"{year:04d}-{month:02d}-{day:02d}"
        if best is None or iso > best:
            best = iso
    return best


def _revision_of(reg: dict) -> dict:
    """규정 1건의 (로컬, 사이트) 최신 날짜를 구한다. 워커 프로세스에서 실행."""
    # playwright 는 --check-revisions 경로에서만 필요하므로 지연 import 한다.
    from parse_preview import parse_preview

    result = {
        "name": reg["name"],
        "file_no": reg["file_no"],
        "local_path": reg.get("local_path"),
        "local_date": None,
        "site_date": None,
        "error": None,
    }
    errors: list[str] = []

    path = reg.get("local_path")
    if not path:
        errors.append("local_path 미등록")
    else:
        full = REPO_ROOT / path
        if full.exists():
            result["local_date"] = latest_date(full.read_text(encoding="utf-8"))
        else:
            errors.append(f"파일 없음: {path}")

    # 미리보기 페이지는 간헐적으로 networkidle 타임아웃이 난다 — 한 번 재시도한다.
    for attempt in range(REVISION_PARSE_ATTEMPTS):
        try:
            result["site_date"] = latest_date(parse_preview(reg["file_no"]).markdown)
            break
        except Exception as exc:  # noqa: BLE001 - 파싱 실패는 개별 규정만 건너뛴다
            if attempt == REVISION_PARSE_ATTEMPTS - 1:
                errors.append(f"미리보기 파싱 실패: {type(exc).__name__}: {exc}"[:200])

    result["error"] = " / ".join(errors) or None
    return result


def check_revisions(stored: list[dict], workers: int) -> tuple[list[dict], list[dict]]:
    """미리보기 본문의 최신 개정일과 로컬 마크다운을 대조한다.

    fileNo 는 개정돼도 유지되는 경우가 있어 compare() 만으로는 본문 개정을
    감지하지 못한다.

    Returns:
        (revised, unknown) — revised 는 사이트가 더 최신인 규정,
        unknown 은 어느 한쪽 날짜를 구하지 못해 판정 불가인 규정.
    """
    revised: list[dict] = []
    unknown: list[dict] = []

    with ProcessPoolExecutor(max_workers=workers) as pool:
        for r in pool.map(_revision_of, stored):
            if r["local_date"] and r["site_date"]:
                if r["site_date"] > r["local_date"]:
                    revised.append(r)
            else:
                unknown.append(r)

    revised.sort(key=lambda r: r["site_date"], reverse=True)
    return revised, unknown


def print_revision_report(revised: list[dict], unknown: list[dict], total: int) -> None:
    print(f"개정일자 대조: {total}건 검사")
    print()

    if revised:
        print(f"=== 본문 개정 ({len(revised)}건) ===")
        for r in revised:
            print(f"  {r['name']} (fileNo={r['file_no']})")
            print(f"    로컬 {r['local_date']} → 사이트 {r['site_date']}")
        print()
    else:
        print("본문 개정 없음")
        print()

    if unknown:
        print(f"=== 판정 불가 ({len(unknown)}건) ===")
        for r in unknown:
            print(
                f"  {r['name']} (fileNo={r['file_no']}) "
                f"로컬={r['local_date']} 사이트={r['site_date']} — {r['error'] or '날짜 없음'}"
            )
        print()


def print_text_report(
    changed: list[dict],
    new: list[dict],
    removed: list[dict],
    web_count: int,
    stored_count: int,
) -> None:
    print(f"웹사이트 규정 수: {web_count}개")
    print(f"저장된 규정 수: {stored_count}개")
    print()

    if not changed and not new and not removed:
        print("변경 사항 없음")
        return

    if changed:
        print(f"=== fileNo 변경 ({len(changed)}건) ===")
        for c in changed:
            print(f"  {c['name']}")
            print(f"    {c['old_file_no']} → {c['new_file_no']}")
        print()

    if new:
        print(f"=== 신규 규정 ({len(new)}건) ===")
        for n in new:
            print(f"  {n['name']} (fileNo={n['file_no']})")
        print()

    if removed:
        print(f"=== 삭제된 규정 ({len(removed)}건) ===")
        for r in removed:
            print(f"  {r['name']} (fileNo={r['file_no']})")
        print()


def print_json_report(
    changed: list[dict],
    new: list[dict],
    removed: list[dict],
    web_count: int,
    stored_count: int,
    duplicate_titles: dict[str, list[int]] | None = None,
    revised: list[dict] | None = None,
    revision_unknown: list[dict] | None = None,
) -> None:
    report = {
        "web_count": web_count,
        "stored_count": stored_count,
        "changed": changed,
        "new": new,
        "removed": removed,
        "duplicate_titles": duplicate_titles or {},
        "revised": revised or [],
        "revision_unknown": revision_unknown or [],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


def apply_updates(
    data: dict,
    changed: list[dict],
    new: list[dict],
    removed: list[dict],
) -> None:
    """변경 사항을 regulations.json에 반영합니다."""
    regulations = data["regulations"]

    # fileNo 변경 적용
    by_old_fno = {c["old_file_no"]: c["new_file_no"] for c in changed}
    for reg in regulations:
        if reg["file_no"] in by_old_fno:
            reg["file_no"] = by_old_fno[reg["file_no"]]

    # 삭제된 규정 제거
    removed_fnos = {r["file_no"] for r in removed}
    regulations = [r for r in regulations if r["file_no"] not in removed_fnos]

    # 신규 규정 추가
    for n in new:
        # domain/audience는 빈 값으로 시딩 — check_quality.py가 태그 누락을 잡는다
        regulations.append({
            "name": n["name"],
            "file_no": n["file_no"],
            "section": "",
            "domain": "",
            "audience": [],
            "local_path": None,
        })

    data["regulations"] = regulations
    data["last_checked"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_regulations(data)

    total = len(changed) + len(new) + len(removed)
    print(f"regulations.json 업데이트 완료 ({total}건 반영)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="KNUE 규정 fileNo 변경 감지 도구"
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="변경 사항을 regulations.json에 반영",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="JSON 형식으로 출력",
    )
    parser.add_argument(
        "--check-revisions",
        action="store_true",
        dest="check_revisions",
        help=(
            "미리보기 본문의 최신 개정일을 로컬 마크다운과 대조 "
            "(fileNo 가 그대로인 개정 감지, 규정 전건 파싱이라 수 분 소요)"
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_REVISION_WORKERS,
        help=f"--check-revisions 병렬 워커 수 (기본 {DEFAULT_REVISION_WORKERS})",
    )
    args = parser.parse_args()

    data = load_regulations()
    stored = data["regulations"]

    web = fetch_web_regulations(data["source_url"])

    if len(web) < MIN_EXPECTED_REGULATIONS:
        print(
            f"경고: 파싱된 규정 수가 {len(web)}개로 너무 적습니다. "
            "웹사이트 구조가 변경되었을 수 있습니다.",
            file=sys.stderr,
        )
        sys.exit(1)

    duplicate_titles = warn_duplicate_titles(web)

    changed, new, removed = compare(stored, web)

    revised: list[dict] = []
    revision_unknown: list[dict] = []
    if args.check_revisions:
        # fileNo 변경분은 마크다운을 어차피 새로 받아야 하므로 대조에서 제외한다.
        changed_fnos = {c["new_file_no"] for c in changed}
        targets = [r for r in stored if r["file_no"] not in changed_fnos]
        revised, revision_unknown = check_revisions(targets, max(1, args.workers))

    if args.json_output:
        print_json_report(
            changed,
            new,
            removed,
            len(web),
            len(stored),
            duplicate_titles,
            revised,
            revision_unknown,
        )
    else:
        print_text_report(changed, new, removed, len(web), len(stored))
        if args.check_revisions:
            print_revision_report(revised, revision_unknown, len(stored) - len(changed))

    if args.update:
        if changed or new or removed:
            apply_updates(data, changed, new, removed)
        else:
            print("변경 사항 없음")


if __name__ == "__main__":
    main()
