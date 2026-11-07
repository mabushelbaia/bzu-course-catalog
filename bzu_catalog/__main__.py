"""bzu-course-catalog: scrape Ritaj's Course Browser into JSON.

    python -m bzu_catalog scrape [--newest N] [--terms 1253 1252] [--out data]
    python -m bzu_catalog parse PAGE.html [--out data]     # parse a saved page, no network

Writes, per semester:
    data/<term>.json              every course, section and meeting
    data/<term>/<PREFIX>.json     the same, one file per course prefix (e.g. ENCS) for small static sites
and data/index.json listing the semesters, their counts and when their data last changed.
A semester's files are only rewritten when its data actually changed, so daily runs that find
nothing new produce no commit.
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import fetch as fetching
from .parse import DAYS, parse_courses, parse_terms, shown_term


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
            if f.stem not in by_prefix:
                f.unlink()
    for prefix, cs in by_prefix.items():
        dump(folder / f"{prefix}.json", {**meta, "prefix": prefix, "counts": counts(cs), "courses": cs})
    index["terms"][code] = {"name": term["name"], "updated_at": stamp, "hash": h, "counts": counts(courses),
                            "prefixes": sorted(by_prefix)}
    c = counts(courses)
    print(f"  {code}: written ({c['courses']} courses, {c['sections']} sections)")
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
    save_index(out, index)


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
    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
