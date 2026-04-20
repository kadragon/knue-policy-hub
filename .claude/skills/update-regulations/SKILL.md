---
name: update-regulations
description: regulation-update 라벨의 열린 GitHub 이슈를 일괄 소비하여 규정 파일과 tools/regulations.json 을 싱크한다. 이슈당 Haiku 서브에이전트를 띄워 미리보기 원문을 저장소 양식으로 재정렬한다. "규정 업데이트", "regulation 이슈 처리", "KNUE 규정 싱크", "regulation-update 반영" 같은 요청에 트리거.
---

# update-regulations

KNUE 주간 워크플로(`check-regulation-updates.yml`)가 생성한 `[규정 변경]` / `[신규 규정]` / `[규정 삭제]` 이슈를 로컬에서 한 번에 처리한다.

- 미리보기 파싱: `tools/parse_preview.py` (Python + Playwright, 로컬 Chromium)
- 마크다운 재정렬: **이슈당 Haiku 서브에이전트** — 원문 파일을 읽고 대상 양식으로 바꾼 뒤 Write 로 직접 저장
- JSON/파일/git 조작: 오케스트레이터(이 스킬을 실행하는 메인 에이전트)가 직접 수행

## 선결 조건

```bash
# working tree clean
git status --porcelain  # 빈 문자열이어야 함

# playwright chromium
uv run --project tools python -c "from playwright.sync_api import sync_playwright" \
  || (cd tools && uv sync && uv run playwright install chromium)

# gh 인증
gh auth status
```

하나라도 실패하면 사용자에게 원인과 해결 방법을 전하고 중단.

## 실행 순서

### 1. 브랜치 준비

```bash
DATE=$(date +%Y-%m-%d)
git switch -c "regulation-sync/$DATE" 2>/dev/null || git switch "regulation-sync/$DATE"
```

### 2. 이슈 수집

```bash
gh issue list --label regulation-update --state open --limit 200 \
  --json number,title,body > /tmp/issues.json
```

각 이슈의 제목 접두사로 유형 분기:
- `[규정 변경]` → change (body: `이전 fileNo`, `새 fileNo`, `분류`)
- `[신규 규정]` → new (body: `fileNo`)
- `[규정 삭제]` → delete (body: `기존 fileNo`, `분류`)

삭제 → 변경 → 신규 순으로 처리(의존성 최소화).

### 3. 삭제 이슈 처리 (per issue)

```bash
# regulations.json 에서 엔트리 조회 (name 또는 file_no 기준)
# Edit 툴로 regulations.json 에서 해당 엔트리 제거
# 파일 시스템에서 local_path 삭제
rm -- "<local_path>"
git add tools/regulations.json "<local_path>"
git commit -m "[FIX] 규정 삭제: <name> (closes #<N>)"
```

### 4. 변경 이슈 처리 (per issue)

```bash
# a) 대상 경로 확인: regulations.json 에서 name/old_file_no 로 엔트리 찾기 → local_path
# b) 미리보기 파싱
uv run --project tools python tools/parse_preview.py --file-no <new_file_no> \
  > "/tmp/raw_<new_file_no>.md"
```

`c)` Haiku 서브에이전트 띄워 재정렬 + Write — 아래 "서브에이전트 프롬프트 템플릿" 사용. `subagent_type: general-purpose`, `model: haiku`.

`d)` 완료 후:
```bash
# Edit 툴로 regulations.json 에서 해당 엔트리의 file_no 를 new_file_no 로 갱신
git add tools/regulations.json "<local_path>"
git commit -m "[FIX] 규정 갱신: <name> (fileNo <old>→<new>, closes #<N>)"
```

### 5. 신규 이슈 처리 (per issue)

1. AskUserQuestion 으로 편/장(section) 결정: `기존 section 후보 + 직접 입력`.
2. 대상 경로: `규정/<section>/<name>.md`. 이미 존재하면 스킵(사용자에게 보고).
3. 파싱: `parse_preview.py --file-no <fileNo>` → `/tmp/raw_<fileNo>.md`
4. Haiku 서브에이전트로 재정렬 + Write (아래 템플릿).
5. Edit 툴로 regulations.json 에 엔트리 추가:
   ```json
   { "name": "<name>", "file_no": <fileNo>, "section": "<section>", "local_path": "규정/<section>/<name>.md" }
   ```
6. `git add` + `git commit -m "[FEAT] 신규 규정: <name> (fileNo=<fileNo>, closes #<N>)"`

### 6. 요약 보고

사용자에게 "done / skipped / failed" 로 분류된 이슈 번호 리스트와 `git log --oneline origin/main..HEAD` 를 제시.

PR/이슈 닫기는 수동. 커밋 메시지에 `closes #N` 이 있어 PR 머지 시 자동 close.

## 서브에이전트 프롬프트 템플릿

이슈당 한 번 호출. 툴 권한: Read, Write 만 허용(Bash 불필요). 모델: `haiku`.

```
당신은 한국 법령/규정 문서 편집기다. 다음 두 파일을 먼저 Read 로 읽어라:
  1. 원문 RAW: <RAW_PATH>  (KNUE 미리보기에서 기계 추출된 중간 마크다운)
  2. 목표 양식 예시: 규정/제1편/제2장/한국교원대학교 대학원 학칙.md  (앞부분만 참고)

그 다음 RAW 를 아래 규칙에 따라 저장소 양식으로 재정렬해 Write 로
<DEST_PATH> 에 저장하라. 저장 후 종료하라.

규정명: <REG_NAME>

핵심 원칙: **RAW 에 명시적으로 존재하는 텍스트만 사용**. 모양을 예시에 맞추려고
새 줄/새 헤더/새 이력을 만들어내지 마라. 불확실하면 생략한다.

엄격한 규칙:
1. 최상단: `# <REG_NAME>` 한 번.
2. 공포/개정 이력:
   - RAW 에 `[시행 ...] [... 제N호, YYYY. M. D., 일부개정]` 형태의 단일 헤더 줄이 있으면 그대로 한 줄로 보존.
   - RAW 에 `제정 YYYY. M. D.` / `개정 YYYY. M. D.(제N호)` 류 독립 줄이 여러 개 나열된 경우에만
     각 줄을 그대로 옮기고, 마지막 줄을 제외한 줄 끝에 두 칸 공백(마크다운 hard break)을 붙인다.
   - 조문 본문 안의 `<개정 YYYY. M. D.>` 주석을 근거로 개정 이력 줄을 새로 만들지 마라.
   - 이력/헤더 다음: 빈 줄 → `---` → 빈 줄.
3. 장(章) 헤더:
   - RAW 에 `제N장 {제목}` 이라는 독립 줄이 실제로 있을 때만 `## 제N장 {제목}` 생성.
   - 없으면 장 헤더를 만들지 마라. 이 경우 조문은 `## 제M조({제목})` 1단 구조.
   - 있으면 조문은 `### 제M조({제목})` 2단 구조.
4. 조문: RAW 의 `제N조(제목) 본문...` / `제N조의M(제목) 본문...` 패턴을 헤더+본문으로 분리.
   항(①②③ / 1. 2. 3.)·호(가. 나. 다.) 표기, `<개정 ...>` / `[본조신설 ...]` / `[제목개정 ...]` 주석은 원문 그대로 보존.
5. `부칙`, `별표`, `별지` 는 본문과 같은 헤더 레벨로 유지. 표(`| ... |`)는 그대로 둔다.
6. 파서 노이즈(조용히 제거 가능): `법제처`, `국가법령정보센터`, `- N / M -`,
   규정명이 본문 시작 전에 중복 반복된 줄, 전화번호 한 줄. 그 외는 버리지 마라.
7. 응답으로 마크다운을 돌려주지 마라. 오직 Write 툴로 <DEST_PATH> 에 저장한 뒤 한 줄 "done" 으로 끝낸다.
```

서브에이전트 호출 시 `<RAW_PATH>` / `<DEST_PATH>` / `<REG_NAME>` 세 자리를 치환.

## 품질 점검 (오케스트레이터 측)

서브에이전트 종료 후 메인 에이전트가 `<DEST_PATH>` 를 Read 로 확인:
- 첫 줄이 `# <REG_NAME>` 으로 시작
- 파일 길이 500자 이상
- `## ` 헤더 최소 1개

셋 중 하나라도 실패하면 해당 이슈는 "failed — 서브에이전트 출력 품질 미달" 로 표시하고 다음과 같이 원복한 뒤 다음 이슈로 진행:
- 변경 이슈: `git restore -- "<DEST_PATH>"` (이전 버전 복원)
- 신규 이슈: `rm -- "<DEST_PATH>"` (git 에 추적 이력 없음)

## 재실행 안전성

각 이슈 처리 전에 선(先)체크로 스킵 여부를 판정해 중복 커밋을 방지한다.

- **변경**: `regulations.json` 의 해당 엔트리 `file_no` 가 이슈의 `새 fileNo` 와 같으면 스킵.
- **신규**: `regulations.json` 에 동일 `file_no` 엔트리가 이미 있거나 `규정/<section>/<name>.md` 가 이미 존재하면 스킵.
- **삭제**: `regulations.json` 에 해당 엔트리가 없고 `local_path` 파일도 없으면 스킵.

## 실패 케이스

- **파싱 실패(본문 0줄)**: `parse_preview.py` 가 exit 1 — 해당 이슈만 스킵.
- **서브에이전트 품질 미달**: 위 점검 기준 중 하나 이상 실패 — 파일 원복 + 스킵.
- **regulations.json 엔트리 부재(변경 이슈)**: `check_updates.py --update` 가 아직 안 돈 것 — 사용자에게 먼저 돌리라고 안내.

## 관련 파일

- `tools/parse_preview.py` — 미리보기 → RAW 마크다운
- `tools/regulations.json` — 규정 인덱스(name/file_no/section/local_path)
- `tools/check_updates.py` — fileNo 변동 감지(주간 워크플로용, 이 스킬이 호출하지는 않음)
