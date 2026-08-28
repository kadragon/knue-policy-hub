# Backlog

Out-of-scope findings from the PR #50 review cycle (feat/regulation-taxonomy).

## [P2] 중복 title 시 자동 업데이트 차단
`check_updates.py`는 중복 노출된 fileNo를 경고만 하고, `check-regulation-updates.yml`은
`duplicate_titles`를 읽지 않은 채 `--update`를 그대로 실행한다. `compare()`가 중복 중 하나를
임의로 골라 기존 `local_path`에 붙이면 이후 덮어쓰기로 이어진다. 중복이 있으면 해당 항목의
자동 시딩을 건너뛰거나 워크플로를 실패시킬 것. (출처: codex P2, code-review #4)

## [P2] parse/reformat 단계에서 원문 제목 검증
`reformat_regulation.py`가 원문 제목 줄을 버리고 호출자가 준 `reg_name`으로 H1을 쓰기 때문에,
본문에 제목이 한 번만 등장하는 규정은 `_check_body_title`이 대조할 근거가 없다. 잘못된 fileNo를
파싱해도 형태상 정상 문서가 나온다. 변환 전에 원문 제목을 검증하거나 보존할 것. (출처: codex P1 #1)

## [P2] reformat: 제목 공백 정규화
2단계(이력 수집)·3단계(본문)에서 제목 일치를 `ln == reg_name`으로 엄격 비교한다. 원문이
`한국교원대학교 자체행정감사규정`처럼 공백이 다르면 이력 파싱이 즉시 중단되어 제·개정 이력과
`---` 구분선이 누락된다. `_norm()`(공백 제거) 비교로 바꿀 것. (출처: agy P2)

## [P3] update-regulations 스킬: Playwright 중복 fetch
신규 규정 이슈마다 step 0(규정명 확인)과 step 3(본문 파싱)이 같은 미리보기를 두 번 스크랩한다.
step 3에서 한 번만 파싱한 뒤 첫 줄을 이슈의 `<name>`과 대조하도록 합칠 것. (출처: code-review P3)
