"""Parses Ritaj's public Course Browser page into plain data.

Ported from dept-ops' `catalog/management/commands/parse_catalog.py`, without the database layer.
The page lists every course of a semester: a course header row, then one row per section with the
instructor, enrolment and a nested table of meetings (days, time, room; several per cell, split by <br>).
"""

import re

from bs4 import BeautifulSoup

# Ritaj's day letters. Birzeit's teaching week is Saturday to Thursday.
DAYS = {"S": "Sat", "U": "Sun", "M": "Mon", "T": "Tue", "W": "Wed", "R": "Thu"}
_JOINED = {"TR": " T R ", "MW": " M W ", "WS": " W S ", "SM": " S M ", "MT": " M T "}


def parse_days(text: str) -> list[str]:
    if not text:
        return []
    text = text.replace(",", " ")
    for joined, spaced in _JOINED.items():
        text = text.replace(joined, spaced)
    return [d for d in (p.strip().upper() for p in text.split()) if d in DAYS]


def parse_time(text: str) -> tuple[str | None, str | None]:
    m = re.match(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", (text or "").strip())
    if not m:
        return None, None
    return f"{int(m.group(1)):02d}:{m.group(2)}", f"{int(m.group(3)):02d}:{m.group(4)}"


def parse_enrolment(text: str) -> tuple[int, int | None]:
    """'19/30' -> (19, 30); '19' -> (19, None)."""
    numbers = [int(n) for n in re.findall(r"\d+", text or "")]
    if len(numbers) >= 2:
        return numbers[0], numbers[1]
    if numbers:
        return numbers[0], None
    return 0, None


def split_room(room: str) -> tuple[str, str]:
    """'Masri108' -> ('Masri', '108')."""
    m = re.match(r"^([A-Za-z.]+)\s*(\d+\w*)$", room.strip())
    return (m.group(1), m.group(2)) if m else ("", room.strip())


def _cell_parts(cell) -> list[str]:
    parts = re.split(r"<br\s*/?>", str(cell), flags=re.IGNORECASE)
    return [BeautifulSoup(p, "lxml").get_text(" ", strip=True) for p in parts]


def parse_terms(html: str) -> list[dict]:
    """The semester list from the page's 'Choose Semester' dropdown, newest first."""
    soup = BeautifulSoup(html, "lxml")
    select = soup.find("select", attrs={"title": "Choose Semester"})
    if not select:
        return []
    terms = []
    for opt in select.find_all("option"):
        code = (opt.get("value") or "").strip()
        if code.isdigit():
            terms.append({"code": code, "name": opt.get_text(strip=True)})
    return terms


def shown_term(html: str) -> str | None:
    """The semester the page actually shows. Ritaj falls back to the current one for unpublished semesters."""
    select = BeautifulSoup(html, "lxml").find("select", attrs={"title": "Choose Semester"})
    opt = select.find("option", selected=True) if select else None
    return (opt.get("value") or "").strip() or None if opt else None


def parse_courses(html: str) -> list[dict]:
    """Every course on the page, each with its sections and their weekly meetings."""
    soup = BeautifulSoup(html, "lxml")
    courses: dict[str, dict] = {}
    current = None

    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")

        # Course header: 4 cells, the first labelled "label nv b"
        if len(cells) == 4:
            classes = cells[0].get("class") or []
            if {"label", "nv", "b"} <= set(classes):
                code = cells[0].get_text(strip=True)
                if code:
                    current = courses.setdefault(code, {
                        "code": code,
                        "prefix": re.match(r"[A-Za-z]*", code).group(0),
                        "name": cells[2].get_text(" ", strip=True),
                        "sections": [],
                    })
                continue

        # Section row: 5+ cells, the first classed "gc alc" (but not a header)
        if len(cells) >= 5 and current is not None:
            classes = set(cells[0].get("class") or [])
            if not ({"gc", "alc"} <= classes) or "light_header" in classes:
                continue
            enrolled, capacity = parse_enrolment(cells[3].get_text(strip=True))
            section = {
                "type": cells[0].get_text(strip=True),
                "number": cells[1].get_text(strip=True),
                "instructor": cells[2].get_text(" ", strip=True) or None,
                "enrolled": enrolled,
                "capacity": capacity,
                "meetings": [],
            }
            table = cells[4].find("table")
            for row in (table.find_all("tr") if table else []):
                sc = row.find_all("td")
                if len(sc) < 3:
                    continue
                days, times, rooms = _cell_parts(sc[0]), _cell_parts(sc[1]), _cell_parts(sc[2])
                for i in range(max(len(days), len(times), len(rooms))):
                    day_text = days[i] if i < len(days) else ""
                    start, end = parse_time(times[i] if i < len(times) else "")
                    room = (rooms[i] if i < len(rooms) else "").strip()
                    if room.lower() in ("", "n/a", "na", "tba", "tbc"):
                        room = None
                    building, number = split_room(room) if room else ("", "")
                    for day in parse_days(day_text):
                        section["meetings"].append({
                            "day": day,
                            "start": start,
                            "end": end,
                            "room": room,
                            "building": building or None,
                        })
            current["sections"].append(section)

    return sorted(courses.values(), key=lambda c: c["code"])


# --- Academic calendar -------------------------------------------------------------------------
# Ritaj's public academic calendar (one page per academic year) lists dated events in Arabic, in a
# table grouped by month: <td id="mon_10_2026"> starts a month, then each row has the day and the
# events. We keep the four dates that bound a semester.

CALENDAR_URL = "https://ritaj.birzeit.edu/be1/en/academic/academic-calendar/public-academic-calendar?academic-year={start}%2F{end}"

# The semester as the calendar names it, by the last digit of the term code
_SEMESTER = {"1": "للفصل الدراسي الأول", "2": "للفصل الدراسي الثاني", "3": "للدورة الصيفية"}
_EVENTS = {
    "teaching_starts": "بدء التدريس",
    "teaching_ends": "آخر يوم تدريس",
    "exams_start": "بدء فترة الامتحانات النهائية",
    "exams_end": "انتهاء فترة الامتحانات النهائية",
}


def academic_year(term: str) -> tuple[int, int]:
    """Term 1261 is First Semester 2026/2027: the first three digits are the year minus 1900."""
    start = 1900 + int(term[:3])
    return start, start + 1


def parse_calendar(html: str) -> list[tuple[str, str]]:
    """Every dated event on the page, as (YYYY-MM-DD, text), in page order."""
    soup = BeautifulSoup(html, "lxml")
    events, month = [], None
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td", recursive=False)
        for td in cells:
            m = re.fullmatch(r"mon_(\d+)_(\d{4})", td.get("id") or "")
            if m:
                month = (int(m.group(2)), int(m.group(1)))
        day = next((int(t) for td in cells if (t := td.get_text(strip=True)).isdigit()), None)
        if not month or day is None:
            continue
        for p in tr.find_all("p"):
            text = " ".join(p.get_text(" ", strip=True).split())
            if text:
                events.append((f"{month[0]:04d}-{month[1]:02d}-{day:02d}", text))
    return events


def term_dates(events: list[tuple[str, str]], term: str) -> dict:
    """Teaching and exam dates for one term, from the calendar events. Missing ones are left out."""
    start, end = academic_year(term)
    semester = f"{_SEMESTER[term[-1]]} {start}/{end}"
    out = {}
    for key, phrase in _EVENTS.items():
        for date, text in events:
            if text.startswith(phrase) and semester in text:
                out[key] = date
                break
    return out


# --- Faculties and departments ----------------------------------------------------------------
# Ritaj's unit tree (hemis/bu/hierarchy) nests faculties, departments and, under each department,
# its programs: "Bachelor Level Courses of Computer Engineering ENCS". The last word of a program is
# its course prefix. Some programs sit straight under a faculty, or at the top of the tree.

HIERARCHY_URL = "https://ritaj.birzeit.edu/hemis/bu/hierarchy?mode=CB&lang=en"

_PROGRAM = re.compile(r"^(?P<level>.+?) Level Courses of (?P<name>.+?)\s+(?P<prefix>[A-Z]{2,6})$")


_SMALL = {"and", "of", "the", "in", "for", "&"}


def _tidy(name: str) -> str:
    """Ritaj's names come in mixed case ("COMPUTER ENGINEERING", "Electrical and computer Engineering"):
    capitalise every word but the small ones."""
    words = " ".join(name.split()).split(" ")
    return " ".join(w.lower() if i and w.lower() in _SMALL else w[:1].upper() + (w[1:].lower() if w.isupper() else w[1:])
                    for i, w in enumerate(words))


def _unit_label(li) -> str:
    head = li.find(class_="tree_header")
    if head is None:
        return ""
    if head.name != "div" or head.find("a"):
        head = head.find("a") or head
    return " ".join(head.get_text(" ", strip=True).split())


def _program(uid: str, label: str) -> dict | None:
    m = _PROGRAM.match(label)
    if not m:
        return None  # a program with no course prefix (e.g. an associate diploma) has nothing to show
    return {"id": uid, "level": m["level"], "name": _tidy(m["name"]), "prefix": m["prefix"]}


def parse_hierarchy(html: str) -> dict:
    """Faculties, their departments and each department's programs (with course prefixes).

    Programs that sit straight under a faculty go in the faculty's own "programs"; ones at the top of
    the tree (general university courses) in the top-level "programs".
    """
    soup = BeautifulSoup(html, "lxml")
    tree = soup.find(id="treeview_div")
    top = tree.find("ul", recursive=False) if tree else None
    out = {"faculties": [], "programs": []}
    if top is None:
        return out

    def units(ul):
        for li in ul.find_all("li", recursive=False):
            yield li.get("id") or "", _unit_label(li), li.find("ul", recursive=False)

    for fid, fname, fsub in units(top):
        if fsub is None:
            p = _program(fid, fname)
            if p:
                out["programs"].append(p)
            continue
        faculty = {"id": fid, "name": _tidy(fname), "departments": [], "programs": []}
        for did, dname, dsub in units(fsub):
            if dsub is None:
                p = _program(did, dname)
                if p:
                    faculty["programs"].append(p)
                continue
            programs = [p for uid, label, _ in units(dsub) if (p := _program(uid, label))]
            faculty["departments"].append({"id": did, "name": _tidy(dname), "programs": programs})
        out["faculties"].append(faculty)
    return out
