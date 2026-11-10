"""bzu-course-catalog: scrape Ritaj's Course Browser into JSON.

    python -m bzu_catalog scrape [--newest N] [--terms 1253 1252] [--out data]
    python -m bzu_catalog parse PAGE.html [--out data]     # parse a saved page, no network

Writes, per semester:
    data/<term>.json              every course, section and meeting
    data/<term>/<PREFIX>.json     the same, one file per course prefix (e.g. ENCS) for small static sites
    data/<term>/rooms.json        every department's meetings grouped by room (rooms are shared)
and data/departments.json: Ritaj's faculties and departments with each one's programs and course prefixes,
and data/index.json listing the semesters, their counts, when their data last changed, their
teaching and exam dates from Ritaj's academic calendar, the semester in progress (current), and
when Ritaj was last checked (checked_at, stamped on every scrape). A semester's files are only
rewritten when its data actually changed; a run that finds nothing new only updates checked_at.
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import fetch as fetching
from .parse import CALENDAR_URL, DAYS, HIERARCHY_URL, academic_year, parse_calendar, parse_courses, parse_hierarchy, parse_terms, shown_term, term_dates


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def counts(courses: list[dict]) -> dict:
    sections = [s for c in courses for s in c["sections"]]
    return {
        "courses": len(courses),
        "sections": len(sections),
        "instructors": len({s["instructor"] for s in sections if s["instructor"]}),
        "rooms": len({m["room"] for s in sections for m in s["meetings"] if m["room"]}),
    }


def rooms_of(courses: list[dict]) -> dict:
    """Every meeting of every department, grouped by room: a room is shared across departments, so a
    room's real week needs all of them. Compact rows: [code, section, instructor, day, start, end]."""
    rooms: dict[str, list] = {}
    for c in courses:
        for s in c["sections"]:
            for m in s["meetings"]:
                if m["room"] and m["start"]:
                    rooms.setdefault(m["room"], []).append([c["code"], s["number"], s["instructor"], m["day"], m["start"], m["end"]])
    return {r: sorted(v, key=lambda x: ("SUMTWRF".find(x[3]), x[4], x[0])) for r, v in sorted(rooms.items())}


def write_rooms(folder: Path, meta: dict, courses: list[dict]) -> None:
    dump(folder / "rooms.json", {**meta, "rooms": rooms_of(courses)})


def write_term(out: Path, index: dict, term: dict, courses: list[dict], source: str) -> bool:
    """Writes one semester if its data changed. Returns True when files were written."""
    code = term["code"]
    old = index["terms"].get(code, {})
    if not courses and old.get("counts", {}).get("courses"):
        # A page that suddenly parses to nothing is a broken fetch or a layout change, not an empty semester.
        raise SystemExit(f"Refusing to replace {code}: parsed 0 courses, previously {old['counts']['courses']}")
    h = digest(courses)
    if h == old.get("hash"):
        print(f"  {code}: unchanged")
        # Semesters written before rooms.json existed get it once
        if not (out / code / "rooms.json").exists() and courses:
            write_rooms(out / code, {"term": code, "name": term["name"], "updated_at": old.get("updated_at"), "source": source, "days": DAYS}, courses)
        return False
    stamp = now()
    meta = {"term": code, "name": term["name"], "updated_at": stamp, "source": source, "days": DAYS}
    dump(out / f"{code}.json", {**meta, "counts": counts(courses), "courses": courses})
    by_prefix: dict[str, list] = {}
    for c in courses:
        by_prefix.setdefault(c["prefix"] or "OTHER", []).append(c)
    folder = out / code
    if folder.exists():
        for f in folder.glob("*.json"):
            if f.stem not in by_prefix and f.stem != "rooms":
                f.unlink()
    written = 0
    for prefix, cs in by_prefix.items():
        f = folder / f"{prefix}.json"
        # Leave a prefix's file alone when its courses didn't change, so one department's edit
        # doesn't rewrite every other department's file
        if f.exists():
            try:
                if digest(json.loads(f.read_text(encoding="utf-8")).get("courses")) == digest(cs):
                    continue
            except ValueError:
                pass
        dump(f, {**meta, "prefix": prefix, "counts": counts(cs), "courses": cs})
        written += 1
    write_rooms(folder, meta, courses)
    index["terms"][code] = {"name": term["name"], "updated_at": stamp, "hash": h, "counts": counts(courses),
                            "prefixes": sorted(by_prefix)}
    c = counts(courses)
    print(f"  {code}: written ({c['courses']} courses, {c['sections']} sections; {written} of {len(by_prefix)} prefix files changed)")
    return True


def load_index(out: Path) -> dict:
    p = out / "index.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"source": fetching.COURSES_URL.split("?")[0], "terms": {}, "available_terms": []}


def save_index(out: Path, index: dict) -> None:
    index["terms"] = dict(sorted(index["terms"].items(), reverse=True))
    dump(out / "index.json", index)


def cmd_scrape(args) -> None:
    out = Path(args.out)
    index = load_index(out)
    fetching.wait_for_flaresolverr()
    pages: dict[str, tuple[str, str]] = {}

    def get(code: str) -> tuple[str, str] | None:
        """The page for a semester, or None when Ritaj hasn't published it (it shows another one instead)."""
        if code not in pages:
            url, html = fetching.fetch_term(code)
            shown = shown_term(html)
            # Keep whatever page came back under the semester it really shows, to avoid fetching it twice
            if shown:
                pages.setdefault(shown, (fetching.COURSES_URL.format(term=shown), html))
            if shown != code:
                pages.setdefault(code, None)
        return pages.get(code)

    # Any page carries the full semester list; start from the newest one we know of
    seed = args.terms[0] if args.terms else (index["available_terms"][0]["code"] if index["available_terms"] else "1253")
    get(seed)
    html = next((p[1] for p in pages.values() if p), "")
    terms = parse_terms(html)
    if terms:
        index["available_terms"] = terms
    names = {t["code"]: t["name"] for t in terms}

    done = []
    for code in (args.terms or [t["code"] for t in terms]):
        if not args.terms and len(done) >= args.newest:
            break
        page = get(code)
        if page is None:
            print(f"  {code}: not published yet, skipped")
            continue
        url, h = page
        write_term(out, index, {"code": code, "name": names.get(code, code)}, parse_courses(h), url)
        done.append(code)
    index["published_terms"] = done
    add_calendar(index, done)
    write_departments(out)
    # Stamped on every run, changed or not: shows the data is still being checked, and the daily
    # commit keeps the repo active so GitHub never pauses the scheduled workflow (it does after 60 quiet days)
    index["checked_at"] = now()
    save_index(out, index)


def write_departments(out: Path, html: str | None = None, source: str | None = None) -> None:
    """data/departments.json: faculties, departments and their course prefixes, from Ritaj's unit tree.

    Rewritten only when the tree changed. A tree that can't be fetched or parses to nothing keeps the
    last file; it never fails the scrape.
    """
    try:
        if html is None:
            source, html = fetching.fetch_hierarchy()
    except fetching.FetchError as e:
        print(f"  departments: skipped ({e})")
        return
    tree = parse_hierarchy(html)
    if not tree["faculties"]:
        print("  departments: parsed none, kept the last file")
        return
    path = out / "departments.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if digest({k: old.get(k) for k in tree}) == digest(tree):
        print("  departments: unchanged")
        return
    dump(path, {"updated_at": now(), "source": source, **tree})
    n = sum(len(f["departments"]) for f in tree["faculties"])
    print(f"  departments: written ({len(tree['faculties'])} faculties, {n} departments)")


def add_calendar(index: dict, terms: list[str]) -> None:
    """Teaching and exam dates per semester from Ritaj's academic calendar, and which one is on now.

    A calendar that can't be fetched keeps the dates from the last run; it never fails the scrape.
    """
    pages: dict[tuple[int, int], list] = {}
    for code in terms:
        year = academic_year(code)
        if year not in pages:
            try:
                url, html = fetching.fetch_calendar(*year)
                pages[year] = parse_calendar(html)
                print(f"  calendar {year[0]}/{year[1]}: {len(pages[year])} events")
            except fetching.FetchError as e:
                print(f"  calendar {year[0]}/{year[1]}: skipped ({e})")
                pages[year] = []
        dates = term_dates(pages[year], code)
        if dates and code in index["terms"]:
            index["terms"][code]["calendar"] = {**dates, "source": CALENDAR_URL.format(start=year[0], end=year[1])}
    # The semester in progress: teaching has started and its exams haven't ended. Between semesters,
    # the one that ended most recently, so "this semester" numbers still mean something.
    today = datetime.now(timezone.utc).date().isoformat()
    dated = [(c, t["calendar"]) for c, t in index["terms"].items() if t.get("calendar", {}).get("teaching_starts")]
    started = sorted([x for x in dated if x[1]["teaching_starts"] <= today], key=lambda x: x[1]["teaching_starts"])
    if started:
        code, cal = started[-1]
        index["current"] = {"term": code, "name": index["terms"][code]["name"], **{k: v for k, v in cal.items() if k != "source"}}


def cmd_parse(args) -> None:
    out = Path(args.out)
    index = load_index(out)
    html = Path(args.page).read_text(encoding="utf-8", errors="ignore")
    terms = parse_terms(html)
    from bs4 import BeautifulSoup
    sel = BeautifulSoup(html, "lxml").find("option", selected=True)
    code = (sel.get("value") or "").strip() if sel else "unknown"
    name = sel.get_text(strip=True) if sel else code
    if terms:
        index["available_terms"] = terms
    write_term(out, index, {"code": code, "name": name}, parse_courses(html), f"file:{Path(args.page).name}")
    save_index(out, index)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="bzu_catalog", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scrape", help="fetch semesters from Ritaj through FlareSolverr")
    s.add_argument("--newest", type=int, default=3, help="how many of the newest semesters (default 3)")
    s.add_argument("--terms", nargs="*", help="explicit semester codes, e.g. 1253 1252")
    s.add_argument("--out", default="data")
    s.set_defaults(func=cmd_scrape)
    q = sub.add_parser("parse", help="parse a saved Course Browser page")
    q.add_argument("page")
    q.add_argument("--out", default="data")
    q.set_defaults(func=cmd_parse)
    d = sub.add_parser("departments", help="parse a saved unit tree page (hemis/bu/hierarchy) into departments.json")
    d.add_argument("page")
    d.add_argument("--out", default="data")
    d.set_defaults(func=lambda a: write_departments(Path(a.out), Path(a.page).read_text(encoding="utf-8"), HIERARCHY_URL))
    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
