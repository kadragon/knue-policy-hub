---
name: update-regulations
description: KNUE 규정 이슈(regulation-update 라벨)를 일괄 소비하여 규정 파일과 tools/regulations.json 을 동기화한다. "규정 업데이트", "regulation 이슈 처리", "KNUE 규정 싱크", "regulation-update 반영" 같은 요청에 트리거.
---

# update-regulations

KNUE 웹사이트 `fileNo` 변동에 대해 주간 워크플로(`check-regulation-updates.yml`)가 생성한 `regulation-update` 라벨 이슈를 일괄 처리하는 스킬. 미리보기 파싱은 Python + Playwright, 마크다운 재정렬은 로컬 `ollama gemma4:e4b` 를 사용한다.

## 처리 대상 이슈 유형

- `[규정 변경]` → 기존 `local_path` 파일 덮어쓰기 + `regulations.json` file_no 갱신
- `[신규 규정]` → 신규 파일 생성 + JSON 엔트리 추가 (section 은 사용자 입력 필요)
- `[규정 삭제]` → 파일 삭제 + JSON 엔트리 제거

## 선결 조건 점검

스킬 실행 전 다음을 확인:

```bash
# 1. ollama 모델
ollama list | grep -q 'gemma4:e4b' || echo 'MISSING: ollama pull gemma4:e4b'

# 2. playwright 브라우저 (최초 1회)
uv run --project tools python -c "from playwright.sync_api import sync_playwright" 2>&1 \
  || (cd tools && uv sync && uv run --project tools playwright install chromium)

# 3. working tree 깨끗한지
git status --porcelain
```

위 3개가 통과하지 않으면 중단하고 사용자에게 해결을 요청.

## 실행

1. **Dry run 먼저**:
   ```bash
   uv run --project tools tools/apply_issues.py --dry-run
   ```
   - 처리할 이슈 목록과 예상 변경을 보여준다. 신규 규정이 있으면 section 을 물어본다.
   - 신규 규정이 있으면 각 이슈의 편/장을 사용자에게 물어 `--section <N>=제X편/제Y장` 플래그로 모아둔다. (AskUserQuestion 활용)

2. **실제 실행**:
   ```bash
   uv run --project tools tools/apply_issues.py \
     --section 23=제1편/제2장 --section 24=제3편/제1장 ...
   ```
   - 자동으로 `regulation-sync/YYYY-MM-DD` 브랜치로 전환.
   - 유형별/파일별로 개별 커밋 생성 (`[FIX] 규정 갱신: ... (closes #N)` 등).
   - 파싱 실패/AI 출력 품질 미달 이슈는 스킵하고 요약에 표시.

3. **결과 확인**:
   ```bash
   git log --oneline origin/main..HEAD
   git diff --stat origin/main..HEAD
   ```
   사용자에게 diff 검토 + PR 생성(`/commit-push-pr` 등) + 이슈 닫기(커밋 메시지에 `closes #N` 이 있어 PR 머지 시 자동 close) 단계는 수동으로 진행하라고 안내.

## 실패 케이스 대응

- **파싱 실패 (본문 추출 0줄)**: 해당 이슈만 스킵. 수동 처리 필요.
- **AI 출력 품질 미달 (H1 없음 / 짧음 / H2 없음)**: 해당 파일 쓰지 않고 스킵. 로그에 `MANUAL_REVIEW` 로 남는다.
- **regulations.json 에 엔트리가 없는 변경 이슈**: `check_updates.py --update` 가 아직 안 돈 상태. 먼저 돌리라고 안내.

## 관련 파일

- `tools/parse_preview.py` — 미리보기 → RAW 마크다운
- `tools/reformat_with_ollama.py` — RAW → 저장소 양식
- `tools/apply_issues.py` — 오케스트레이터 (이슈 수집 + 분기 + 커밋)
- `tools/check_updates.py` — fileNo 감지(별도, 주간 워크플로용)
