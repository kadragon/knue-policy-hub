# Regulation transcription conventions

## Inline letter spacing

Preserve source spacing within labels and prose. For example, `하 사 관`,
`조 직`, and `구 분` remain spaced in the stored Markdown. The extractor may
collapse repeated whitespace to one space; it must not remove that remaining
space merely because the text looks like a Korean word.

This convention applies across the regulation corpus. It favors a faithful
transcription and avoids maintaining an unverified dictionary of compact labels.
No bulk rewrite of the existing regulation files is needed to adopt it.

## Wrapped table labels

Line boundaries inside a cell are a separate problem from inline letter spacing.
Keep ` / ` between stacked multi-character pieces unless a source-backed
correction identifies one label. Narrow cell width, font weight, or apparent
word shape alone is insufficient evidence.

The extractor accepts exact piece sequences from the document-scoped
`CONFIRMED_WRAPPED_HEADERS` mapping in `tools/parse_preview.py`. These corrections
apply only to a table's first row and only when the entire cell matches. Body
cells, extra annotation pieces, and different source documents keep separators.
The default mapping is empty for unlisted file numbers.

Before adding a correction, verify the official source, record its file number
and exact pieces in `docs/table-parser-followups.md`, and add a regression case
that also checks an ambiguous or unrelated cell. Reverify the source before
carrying a correction to a replacement file number. Do not reuse it automatically.

Existing vertical-Hangul and standalone-middle-dot joining remains unchanged.
Source-backed repairs of transcription defects are permitted; editorial
modernization of spelling, terminology, or spacing requires a separate decision.
