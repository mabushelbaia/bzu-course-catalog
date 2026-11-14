"""Sanity checks on a parsed semester, run before it replaces the published one.

Ritaj can change its page layout, or the bot check can hand back a half-loaded page, and the parser
will still return *something*. These checks catch the shapes that broken parses take: far fewer
courses than last time, or a field (times, instructors, enrolment, course codes) that has gone
missing across the board. A semester that fails keeps its last good files and the run fails, so
GitHub emails the repo owner.

The thresholds sit well below what real semesters show (Nov 2026: 76-85% of sections have a meeting,
98-100% an instructor, 100% of meetings a time, 93-96% a room, 100% an enrolment figure).
"""

import re

CODE = re.compile(r"^[A-Z]{2,6}\d{3,4}[A-Z]?$")

# Shares below these mean the column was lost, not that the semester is unusual
MIN_SHARE = {
    "sections with a meeting": 0.40,
    "sections with an instructor": 0.60,
    "meetings with a time": 0.70,
    "meetings with a room": 0.50,
    "sections with an enrolment figure": 0.60,
    "courses with a well-formed code": 0.95,
}
# A semester can shrink a little between runs (sections cancelled), never by half
MIN_KEPT = 0.5


def shares(courses: list[dict]) -> dict[str, float]:
    sections = [s for c in courses for s in c["sections"]]
    meetings = [m for s in sections for m in s["meetings"]]

    def share(items, ok):
        return sum(1 for x in items if ok(x)) / len(items) if items else 1.0

    return {
        "sections with a meeting": share(sections, lambda s: s["meetings"]),
        "sections with an instructor": share(sections, lambda s: s["instructors"]),
        "meetings with a time": share(meetings, lambda m: m["start"] and m["end"]),
        "meetings with a room": share(meetings, lambda m: m["room"]),
        "sections with an enrolment figure": share(sections, lambda s: s["enrolled"] is not None),
        "courses with a well-formed code": share(courses, lambda c: CODE.match(c["code"] or "")),
    }


def problems(courses: list[dict], previous: dict | None = None) -> list[str]:
    """What looks wrong with a parsed semester, compared with its last published counts. Empty when fine."""
    previous = previous or {}
    found = []
    sections = sum(len(c["sections"]) for c in courses)
    if not courses:
        # Only a problem when the semester used to have courses; a new one can start empty
        if previous.get("courses"):
            found.append(f"parsed 0 courses, previously {previous['courses']}")
        return found
    for what, now in (("courses", len(courses)), ("sections", sections)):
        before = previous.get(what)
        if before and now < before * MIN_KEPT:
            found.append(f"{what} fell from {before} to {now}")
    for what, share in shares(courses).items():
        if share < MIN_SHARE[what]:
            found.append(f"only {share:.0%} of {what} (expected at least {MIN_SHARE[what]:.0%})")
    if sum(1 for c in courses if not c["sections"]) > len(courses) / 2:
        found.append("most courses have no sections")
    return found
