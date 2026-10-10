# Table parser follow-up verification

Date: 2026-10-10

## Implemented safeguards

- Preserve an occupied rowspan slot when a later colspan overlaps it.
- Join standalone middle-dot pieces in a wrapped label. Join single Hangul
  characters, but keep single numeric and Latin values separated.
- Reject RAW input whose source title differs from the expected regulation.
  Ignore spacing differences and an explicit trailing ` 전문` label. Accept a
  separately supplied `--source-name` for an index entry with `official_name`,
  and preserve that official title beneath the repository H1.
- Recognize `변경` history lines and appendix identifiers such as `제2의2호`.
- Check area-unit normalization at the Markdown quality gate, including content
  inserted outside the RAW conversion path.
- Skip changed/new/deleted candidates whose website title is duplicated. The
  local index remains unchanged until the preview resolves that identity.
- Fetch a new regulation preview once in the update-regulations skill.
- Wait for the Synap viewer's observed completion signal instead of treating a
  stable text length as proof that the document finished loading. A stalled
  viewer fails before returning any Markdown.

## Source-backed document repairs

Seventeen regulations were changed. Horizontal-span repetitions were removed,
misaligned rows in the education-graduate rules were restored, the school rules
were given their actual tables, revision histories were normalized, and missing
forms were restored for housing, intellectual property, employee conduct,
overseas travel, and facility use. Housing articles 11–18 were also absent from
the stored document and were restored from the complete official preview.

The school rules viewer exposes only 15 of its declared 46 pages. Its official
HWP was downloaded from
`https://www.knue.ac.kr/downloadContentsFile.do?key=392&fileNo=1598` and converted
with an isolated `pyhwp` tool environment:

```sh
uv tool run --from pyhwp --with six --with lxml hwp5html \
  --html --output /tmp/knue-policy-followups/1598.hwp.html \
  /tmp/knue-policy-followups/1598.hwp
```

All six original HWP tables matched unique, contiguous ranges of the stored text
after removing whitespace and Markdown punctuation. Only those ranges were
replaced; unrelated school-rule prose was retained. This was a one-time recovery,
not a new runtime dependency or an automatic HWP fallback.

The previously reported space-management header defect was disproved by the
official preview and a screenshot: `교양(공통)강의실` is the parent of two separate
columns, `기본` and `배정`. Its existing folded headers were retained.

## Verification

- 32 local regression tests pass, including delayed/incomplete viewer loading,
  ambiguous-title comparisons, source identity, numeric lists, and table spans.
- Ruff passes with the repository CI flags.
- All 97 indexed Markdown files pass the full quality gate.
- A source-cell audit checks 2,565 nonempty HTML/HWP table cells against the 17
  changed documents. 2,562 cell texts remain contiguous after whitespace and
  Markdown punctuation normalization. The remaining three source cells are the
  education-graduate grading columns, which the stored document expresses as ten
  rows. All ten grade/range/point triples were checked against those columns;
  the conventional `0`/Greek `ο` glyph difference was normalized for that check.
- No distinct numeric token from the pre-change versions of the 17 documents is
  absent after the repairs. This is an additional loss check, not proof of every
  number's row/column association; source-backed table comparison supplies that
  association check.
- Live parsing succeeds for space management (927), graduate degree conferral
  (1584), student researchers (1597), education-graduate rules (1655), and
  intellectual property (946).
- The live regulation list contains 97 entries and reports no file-number
  changes. Duplicate website labels remain visible in the JSON report.

These checks address the recorded parser/document findings. They are not a fresh
revision-date audit of all 97 regulations. Remaining limits are in `backlog.md`.

## Remaining parser limits

- Multi-character wrapped labels: preserve the separator unless the source
  unambiguously identifies one label. Narrow cell width alone cannot distinguish
  `입학인재` + `관리과` from a list such as `합격` / `불합격`. The confirmed
  `입학인재관리과` header was corrected in the finance regulation; no general
  concatenation heuristic was introduced. Implementation: `tools/extract_body.js`.
- Inline letter spacing: decide whether published labels such as `하 사 관`,
  `조 직`, and `구 분` should be shortened consistently across the corpus. This is
  an editorial convention; the parser currently preserves source spacing.
- Automated HWP fallback: the school rules preview still stops after page 15
  of 46. Six tables were recovered from the official HWP download and checked
  against the stored text. Future unattended updates now reject incomplete
  previews; an automatic HWP conversion path remains a separate integration task.
