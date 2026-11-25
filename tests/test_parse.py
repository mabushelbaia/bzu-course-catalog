import json
"""Parser checks against a saved Course Browser page (Summer 2025/2026, from dept-ops' seed data)."""

from pathlib import Path

from bzu_catalog.parse import parse_courses, parse_days, parse_enrolment, parse_terms, parse_time, split_instructors

HTML = (Path(__file__).parent / "fixtures" / "1253.html").read_text(encoding="utf-8", errors="ignore")


def test_whole_page():
    courses = parse_courses(HTML)
    sections = [s for c in courses for s in c["sections"]]
    # Same totals dept-ops' parser reports for this page
    assert len(courses) == 317
    assert len(sections) == 530


def test_one_course():
    c = next(c for c in parse_courses(HTML) if c["code"] == "ENCS3320")
    assert c["prefix"] == "ENCS"
    assert c["name"] == "COMPUTER NETWORKS"
    s = c["sections"][0]
    assert s["instructor"] == "Mohammad Khaleel Issa Jubran"
    assert [m["day"] for m in s["meetings"]] == ["M", "T", "W", "R"]
    assert s["meetings"][0] == {"day": "M", "start": "10:00", "end": "10:50", "room": "Masri109", "building": "Masri"}


def test_terms():
    terms = parse_terms(HTML)
    assert terms[0]["code"] == "1263"
    assert {"code": "1253", "name": "Summer Course 2025/2026"} in terms


def test_helpers():
    assert parse_days("TR") == ["T", "R"]
    assert parse_days("M,W") == ["M", "W"]
    assert parse_time("8:00 - 9:50") == ("08:00", "09:50")
    assert parse_time("") == (None, None)
    assert parse_enrolment("19/30") == (19, 30)
    assert parse_enrolment("19") == (19, None)


def test_calendar():
    from bzu_catalog.parse import academic_year, parse_calendar, term_dates

    html = (Path(__file__).parent / "fixtures" / "calendar-2026-2027.html").read_text(encoding="utf-8")
    events = parse_calendar(html)
    assert academic_year("1261") == (2026, 2027)
    assert term_dates(events, "1261") == {
        "teaching_starts": "2026-10-06", "teaching_ends": "2027-01-28",
        "exams_start": "2027-01-30", "exams_end": "2027-02-14",
    }
    # The second semester starts on 20 February; next year's first semester isn't mistaken for this one's
    assert term_dates(events, "1262")["teaching_starts"] == "2027-02-20"
    assert set(term_dates(events, "1263")) == {"teaching_starts", "teaching_ends", "exams_start", "exams_end"}


def test_calendar_events():
    from bzu_catalog.parse import describe_calendar, parse_calendar

    html = (Path(__file__).parent / "fixtures" / "calendar-2026-2027.html").read_text(encoding="utf-8")
    events = describe_calendar(parse_calendar(html))
    by = lambda title: [e for e in events if e["title"] == title]
    # Every event on this year's page is recognised, and keeps Ritaj's text
    assert all(e["title"] and e["ar"] for e in events)
    assert [e["date"] for e in events] == sorted(e["date"] for e in events)
    # A holiday over several days is one event with an end date; its "end" row is folded in
    xmas = by("Christmas (Western) and winter break")
    assert len(xmas) == 1 and xmas[0]["date"] == "2026-12-24" and xmas[0]["end"] == "2027-01-01"
    assert by("Eid al-Fitr")[0] == {**by("Eid al-Fitr")[0], "date": "2027-03-09", "end": "2027-03-11", "expected": True}
    assert not any(e["ar"].startswith("انتهاء عطلة") for e in events)
    # Make-up days, deadlines and their semester
    assert by("Classes follow the Saturday timetable")[0]["date"] == "2026-10-14"
    drop = by("Last day for late registration and add/drop")
    assert [(e["date"], e["term"]) for e in drop] == [("2026-10-12", "1261"), ("2027-02-27", "1262"), ("2027-07-19", "1263")]
    assert {e["kind"] for e in events} == {"term", "exams", "deadline", "holiday", "swap", "staff", "ceremony"}
    # Next year's first semester is told apart from this year's
    assert by("Teaching starts")[-1] == {**by("Teaching starts")[-1], "date": "2027-09-22", "term": "1271"}


def test_calendar_file_keeps_a_year_it_could_not_fetch(tmp_path):
    from bzu_catalog.__main__ import write_calendar
    from bzu_catalog.parse import parse_calendar

    html = (Path(__file__).parent / "fixtures" / "calendar-2026-2027.html").read_text(encoding="utf-8")
    write_calendar(tmp_path, {(2026, 2027): parse_calendar(html)})
    first = (tmp_path / "calendar.json").read_text(encoding="utf-8")
    write_calendar(tmp_path, {(2026, 2027): []})  # Ritaj unreachable: nothing changes
    assert (tmp_path / "calendar.json").read_text(encoding="utf-8") == first
    assert len(json.loads(first)["years"]["2026/2027"]["events"]) == 52


def test_rooms_cover_every_department():
    from bzu_catalog.__main__ import rooms_of

    rooms = rooms_of(parse_courses(HTML))
    assert rooms["Masri109"]  # a room ENCS3320 meets in
    prefixes = {r[0].rstrip("0123456789") for rs in rooms.values() for r in rs}
    assert len(prefixes) > 10  # not just one department
    assert all(len(r) == 6 and r[4] < r[5] for rs in rooms.values() for r in rs)


def test_departments():
    from bzu_catalog.parse import parse_hierarchy

    tree = parse_hierarchy((Path(__file__).parent / "fixtures" / "hierarchy.html").read_text(encoding="utf-8"))
    eng = next(f for f in tree["faculties"] if f["id"] == "7253")
    assert eng["name"] == "Faculty of Engineering and Technology"
    ece = next(d for d in eng["departments"] if d["id"] == "7261")
    assert ece["name"] == "Department of Electrical and Computer Engineering"
    assert [p["prefix"] for p in ece["programs"]] == ["ENEE", "ENCS", "MSCE"]
    assert ece["programs"][1] == {"id": "10759", "level": "Bachelor", "name": "Computer Engineering", "prefix": "ENCS"}
    # Programs straight under the faculty, and at the top of the tree
    assert {p["prefix"] for p in eng["programs"]} == {"JMEE", "MSAI"}
    assert [p["prefix"] for p in tree["programs"]] == ["UNIV"]
    assert len(tree["faculties"]) == 9


def test_co_taught_instructors():
    assert split_instructors("A B, C D") == ["A B", "C D"]
    assert split_instructors("A B") == ["A B"]
    assert split_instructors(None) == []
    sections = [s for c in parse_courses(HTML) for s in c["sections"]]
    # Every name in a combined cell is counted once, on its own
    assert all(s["instructors"] == split_instructors(s["instructor"]) for s in sections)
    assert not any("  " in (s["instructor"] or "") for s in sections)
