"""KNUE 규정 fileNo 변경 감지 도구.

웹사이트에서 규정 목록을 스크래핑하여 저장된 fileNo와 비교합니다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

REGULATIONS_PATH = Path(__file__).parent / "regulations.json"
MIN_EXPECTED_REGULATIONS = 85


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
) -> None:
    report = {
        "web_count": web_count,
        "stored_count": stored_count,
        "changed": changed,
        "new": new,
        "removed": removed,
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
        regulations.append({
            "name": n["name"],
            "file_no": n["file_no"],
            "section": "",
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

    changed, new, removed = compare(stored, web)

    if args.json_output:
        print_json_report(changed, new, removed, len(web), len(stored))
    else:
        print_text_report(changed, new, removed, len(web), len(stored))

    if args.update:
        if changed or new or removed:
            apply_updates(data, changed, new, removed)
        else:
            print("변경 사항 없음")


if __name__ == "__main__":
    main()
