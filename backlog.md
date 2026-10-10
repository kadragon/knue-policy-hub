# Backlog

Remaining parser limits after the 2026-10-10 follow-up. Completed findings and
verification evidence are recorded in `docs/table-parser-followups.md`.

- [ ] Multi-character wrapped labels: preserve the separator unless the source
  unambiguously identifies one label. Narrow cell width alone cannot distinguish
  `입학인재` + `관리과` from a list such as `합격` / `불합격`. The confirmed
  `입학인재관리과` header was corrected in the finance regulation; no general
  concatenation heuristic was introduced. Owner: `tools/extract_body.js`.
- [ ] Inline letter spacing: decide whether published labels such as `하 사 관`,
  `조 직`, and `구 분` should be shortened consistently across the corpus. This is
  an editorial convention; the parser currently preserves source spacing.
- [ ] Automated HWP fallback: the school rules preview still stops after page 15
  of 46. Six tables were recovered from the official HWP download and checked
  against the stored text. Future unattended updates now reject incomplete
  previews; an automatic HWP conversion path remains a separate integration task.
