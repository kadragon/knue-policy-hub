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
- [ ] [debt] `headerDepth()`가 접지 못한 다단 헤더는 스팬 텍스트를 열마다 반복 출력 — 시설 사용료 종합운동장 표(`구 분` ×4)는 재파싱본이 기존 수작업 표보다 열등해 교체하지 않고 남겨 뒀다. 열마다 반복되는 증상 자체는 스팬 원점 출력으로 해소됐고, 남은 것은 접기 조건 완화 후 재대조 (source: task-next) — `tools/extract_body.js` `headerDepth()`
- [ ] [debt] `joinPieces()`가 3조각 이상 한글 래핑을 붙이지 못한다 — `대위 · 소위`가 `대위 / · / 소위`로, `하 사 관`이 분리된 채 남는다. 적층 값과 래핑 라벨을 가르는 규칙 보강 (source: agy/codex P1 후속) — `tools/extract_body.js` `joinPieces()`
- [ ] [debt] 표 블록을 직접 갈아끼울 때 `reformat_regulation._normalize_chars()`를 거치지 않으면 U+2024·`m2`가 md에 유입된다. RAW→md 경로 밖에서도 정규화가 걸리도록 정리 (source: task-next) — `tools/reformat_regulation.py:78`
- [ ] [debt] `joinPieces()`는 단일 문자 런만 붙인다 — 다중 문자 래핑 라벨(`입학인재` + `관리과`, `부처` + `국본부장`)은 값 목록(`합격`/`불합격`)과 구분할 수 없어 구분자를 유지한다. 스팬/폭 정보 등 텍스트 밖 신호로 판정 가능한지 검토 (source: code-review P1/P2) — `tools/extract_body.js` `joinPieces()`
- [ ] [debt] 공간관리 별표1 헤더 접힘이 열 이름을 오기 — `교양(공통)강의실 / 기본`, `… / 배정`. 원문은 `교양(공통)강의실`과 `기본 배정` 두 열. 헤더 밴드 접기에도 래핑 결합 규칙을 적용할 것 — 다중 문자 래핑 판정에 의존하므로 위 `joinPieces()` 항목이 선행 (source: code-review P2) — `tools/extract_body.js` `headerDepth()`
- [ ] [debt] 가로 스팬 원점 출력 수정을 기존 md 코퍼스에 반영해야 한다 — 인접 중복 셀을 보유한 md 15건(약 233행, 조직 설치 98·대학원 학칙 63·전임교원 임용 22 등)이 수정 전 파서 산출물 상태다. 해당 규정을 재파싱해 표 블록만 교체할 것. 1655/946/1598은 미리보기 불가 항목과 겹침 (source: task-next) — `규정/제3편/제1장/한국교원대학교 조직 설치 규정.md:117`
- [ ] [debt] 면적 단위 통일이 RAW→md 경로에만 걸려 표 밖 본문에는 `m²`가 남는다(공간관리 규정 52행). 기존 코퍼스에 `_normalize_chars()` 일괄 적용하거나 `check_quality.py`에 단위 규칙 추가 (source: code-review P3) — `tools/check_quality.py`

### 대조 결과 기록 (AC2/AC3)

- 재파싱 대조: 표 보유 27건 중 24건 완료. 3건(1655/946/1598)은 사이트 미리보기 뷰어가 본문을 내주지 않아 대조 불가 — 위 항목으로 이월. **AC2는 24/27로 부분 충족.**
- 헤더 접힘 감사: 재파싱본에서 헤더 밴드가 접힌 표 73개 전부에 대해, 교체 전 md의 데이터 셀이 접힘 후에도 남아 있는지 대조 — **삼켜진 데이터 셀 0건**. 접기에 실패해 스팬 텍스트가 열마다 반복된 표는 별도 항목으로 기록.
