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
