"""Fetches Ritaj's public Course Browser through FlareSolverr (no login).

Ritaj sits behind a bot check, so plain HTTP requests are blocked; FlareSolverr runs a real browser,
passes the check and returns the page HTML. This is the same container course-schedule uses, minus
the authenticated session.
"""

import os
import time

import httpx

FLARESOLVERR_URL = os.environ.get("FLARESOLVERR_URL", "http://localhost:8191/v1")
# bu=182 returns every course in the university (all faculties and departments).
COURSES_URL = "https://ritaj.birzeit.edu/hemis/courses?term={term}&bu=182&mode=CB&lang=en"


class FetchError(Exception):
    pass


def wait_for_flaresolverr(retries: int = 30, delay: float = 2.0) -> None:
    for attempt in range(retries):
        try:
            r = httpx.post(FLARESOLVERR_URL, json={"cmd": "sessions.list"}, timeout=10)
            if r.json().get("status") == "ok":
                return
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(delay)
    raise FetchError(f"FlareSolverr did not answer at {FLARESOLVERR_URL}")


def fetch(url: str, attempts: int = 3, marker: str = "Course Browser") -> str:
    last = None
    for i in range(attempts):
        try:
            r = httpx.post(FLARESOLVERR_URL, json={"cmd": "request.get", "url": url, "maxTimeout": 90000}, timeout=150)
            data = r.json()
            sol = data.get("solution") or {}
            if data.get("status") == "ok" and sol.get("status") == 200 and marker in sol.get("response", ""):
                return sol["response"]
            last = f"status={data.get('status')} http={sol.get('status')} message={data.get('message')}"
        except (httpx.HTTPError, ValueError) as e:
            last = repr(e)
        time.sleep(5 * (i + 1))
    raise FetchError(f"Could not fetch {url}: {last}")


def fetch_term(term: str) -> tuple[str, str]:
    url = COURSES_URL.format(term=term)
    return url, fetch(url)


def fetch_hierarchy() -> tuple[str, str]:
    """Ritaj's tree of faculties, departments and their programs."""
    from .parse import HIERARCHY_URL
    return HIERARCHY_URL, fetch(HIERARCHY_URL, marker="treeview_div")


def fetch_calendar(start: int, end: int) -> tuple[str, str]:
    """Ritaj's public academic calendar for one academic year, e.g. 2026/2027."""
    from .parse import CALENDAR_URL
    url = CALENDAR_URL.format(start=start, end=end)
    return url, fetch(url, marker=f"{start}/{end}")
