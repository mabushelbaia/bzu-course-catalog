"""Parser checks against a saved Course Browser page (Summer 2025/2026, from dept-ops' seed data)."""

from pathlib import Path

from bzu_catalog.parse import parse_courses, parse_days, parse_enrolment, parse_terms, parse_time

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
