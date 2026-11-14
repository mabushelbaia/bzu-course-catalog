"""The checks that stop a broken parse from replacing a published semester."""

import copy
from pathlib import Path

from bzu_catalog.check import problems
from bzu_catalog.parse import parse_courses

COURSES = parse_courses((Path(__file__).parent / "fixtures" / "1253.html").read_text(encoding="utf-8", errors="ignore"))


def test_real_page_passes():
    assert problems(COURSES) == []
    assert problems(COURSES, {"courses": 317, "sections": 530}) == []


def test_new_empty_semester_passes():
    assert problems([], None) == []


def test_empty_after_data_fails():
    assert problems([], {"courses": 317}) == ["parsed 0 courses, previously 317"]


def test_half_the_courses_fails():
    found = problems(COURSES[:100], {"courses": 317, "sections": 530})
    assert any("courses fell from 317 to 100" in p for p in found)


def test_lost_column_fails():
    broken = copy.deepcopy(COURSES)
    for c in broken:
        for s in c["sections"]:
            for m in s["meetings"]:
                m["start"] = m["end"] = None
    assert any("meetings with a time" in p for p in problems(broken))


def test_lost_instructors_fails():
    broken = copy.deepcopy(COURSES)
    for c in broken:
        for s in c["sections"]:
            s["instructor"], s["instructors"] = None, []
    assert any("sections with an instructor" in p for p in problems(broken))
