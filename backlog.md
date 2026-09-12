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

## Parser table follow-ups (2차, from fix/parser-table-follow-ups)

- [ ] [debt] 미리보기 뷰어가 본문을 내주지 않는 규정 3건 — 교육대학원 학칙(1655)·지식재산권 규정(946)은 `#content_body`가 빈 채로 렌더링되고, 학칙(1598)은 14페이지에서 렌더링이 멈춰 전체의 31%만 나온다. 표 대조에서 제외됨. 대체 경로(HWP 직접 내려받기 등) 검토 (source: task-next) — `tools/parse_preview.py`
- [ ] [debt] 별지 서식 표 46건이 md에 표로 존재하지 않음 — 교직원 행동강령 13건, 국외출장 16건, 주택관리 5건 등. 재파싱 산출물에는 표로 잡히나 md는 평문. `reformat_regulation.py`의 별지 처리 확인 후 일괄 반영 (source: task-next) — `tools/reformat_regulation.py`
- [ ] [debt] 제·개정 이력이 표로 남은 md 존재(교육정보원 규정 4행 등) — 재파싱 산출물은 이력을 평문으로 뽑으므로 md 쪽이 구형. 이력 블록 정규화 필요 (source: task-next) — `규정/제2편/제1장/한국교원대학교 교육정보원 규정.md:4`
- [ ] [debt] `headerDepth()`가 접지 못한 다단 헤더는 스팬 텍스트를 열마다 반복 출력 — 시설 사용료 종합운동장 표(`구 분` ×4)는 재파싱본이 기존 수작업 표보다 열등해 교체하지 않고 남겨 뒀다. 접기 조건 완화 후 재대조할 것 (source: task-next) — `tools/parse_preview.py:76`
- [ ] [debt] 표 파서 JS(`cellText`/`extractTable`/`headerDepth`, ~150줄)에 자동 테스트가 없다 — 검증이 21개 md 육안 대조뿐. 로컬 HTML fixture → 기대 마크다운 형태의 테스트 추가(적층 값·빈 서식 행·리터럴 슬래시·세로쓰기 케이스) (source: code-review P3) — `tools/parse_preview.py:59`
- [ ] [debt] `joinPieces()`가 3조각 이상 한글 래핑을 붙이지 못한다 — `대위 · 소위`가 `대위 / · / 소위`로, `하 사 관`이 분리된 채 남는다. 적층 값과 래핑 라벨을 가르는 규칙 보강 (source: agy/codex P1 후속) — `tools/parse_preview.py:59`
- [ ] [debt] 표 블록을 직접 갈아끼울 때 `reformat_regulation._normalize_chars()`를 거치지 않으면 U+2024·`m2`가 md에 유입된다. RAW→md 경로 밖에서도 정규화가 걸리도록 정리 (source: task-next) — `tools/reformat_regulation.py:78`

### 대조 결과 기록 (AC2/AC3)

- 재파싱 대조: 표 보유 27건 중 24건 완료. 3건(1655/946/1598)은 사이트 미리보기 뷰어가 본문을 내주지 않아 대조 불가 — 위 항목으로 이월. **AC2는 24/27로 부분 충족.**
- 헤더 접힘 감사: 재파싱본에서 헤더 밴드가 접힌 표 70개 전부에 대해, 교체 전 md의 데이터 셀이 접힘 후에도 남아 있는지 대조 — **삼켜진 데이터 셀 0건**. 접기에 실패해 스팬 텍스트가 열마다 반복된 표는 별도 항목으로 기록.
