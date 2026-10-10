"""Ambiguous website titles must never seed or replace local regulations."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_updates import compare  # noqa: E402


def entry(fno, name):
    return {"file_no": fno, "name": name, "section": "제1편/제1장", "local_path": f"규정/{name}.md"}


def test_duplicate_title_preserves_missing_local_entry_and_skips_seeding():
    stored = [entry(1, "규정 A"), entry(2, "규정 B")]
    changed, new, removed = compare(stored, {3: "규정 A", 4: "규정 A", 5: "규정 B", 6: "규정 C"})
    assert changed == [{"name": "규정 B", "old_file_no": 2, "new_file_no": 5,
                        "section": "제1편/제1장", "local_path": "규정/규정 B.md"}]
    assert new == [{"name": "규정 C", "file_no": 6}]
    assert removed == []


def test_duplicate_title_with_existing_file_number_skips_only_ambiguous_new_entry():
    assert compare([entry(1, "규정 A")], {1: "규정 A", 2: "규정 A"}) == ([], [], [])


def test_unambiguous_deletion_still_reported():
    assert compare([entry(1, "규정 A")], {}) == ([], [], [{"name": "규정 A", "file_no": 1, "section": "제1편/제1장"}])
