# bzu-course-catalog

Birzeit University's course schedules as JSON: every course, section, instructor, room and weekly meeting, scraped once a day from Ritaj's public [Course Browser](https://ritaj.birzeit.edu/hemis/courses?bu=182&mode=CB&lang=en). No login is used.

It feeds the ECE schedule view on [birzeit.me](https://birzeit.me) and the all-departments schedule browser.

## The data

| Path | Contents |
|:--|:--|
| `data/index.json` | The semesters Ritaj offers (`available_terms`), the ones scraped (`published_terms`), when Ritaj was last checked (`checked_at`), and for each semester: name, counts, prefixes and when its data last changed (`updated_at`) |
| `data/<term>.json` | One semester, e.g. `data/1261.json`: every course with its sections and meetings |
| `data/<term>/<PREFIX>.json` | The same, one file per course prefix, e.g. `data/1261/ENCS.json` for a small static site |

Read them straight from GitHub, for example:

```
https://raw.githubusercontent.com/mabushelbaia/bzu-course-catalog/main/data/index.json
https://raw.githubusercontent.com/mabushelbaia/bzu-course-catalog/main/data/1261/ENCS.json
```

A course looks like this (`capacity` is `null` when Ritaj shows enrolment only):

```json
{
 "code": "ENCS3320", "prefix": "ENCS", "name": "COMPUTER NETWORKS",
 "sections": [
  {
   "type": "Lecture", "number": "1", "instructor": "…", "enrolled": 19, "capacity": null,
   "meetings": [{ "day": "M", "start": "10:00", "end": "10:50", "room": "Masri109", "building": "Masri" }]
  }
 ]
}
```

Days use Ritaj's letters: `S` Sat, `U` Sun, `M` Mon, `T` Tue, `W` Wed, `R` Thu. Times are 24-hour.

## How it works

- `bzu_catalog/fetch.py` asks [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr) for the page, since Ritaj is behind a bot check. `bu=182` returns the whole university in one page per semester.
- `bzu_catalog/parse.py` reads the page. It is ported from dept-ops' catalog importer.
- Ritaj lists semesters that aren't published yet; asking for one shows the current semester instead. The scraper notices and skips them, so "newest 3" means the newest 3 published semesters.
- A semester's files are rewritten only when its data changed. Every run stamps `checked_at` in `data/index.json`, so there is one small commit a day even when nothing changed: it shows the data is current, and it keeps GitHub from pausing the schedule (it pauses scheduled workflows in repos with 60 days of no activity). If a page that used to have courses suddenly parses to none, the run fails instead of wiping the data.

`.github/workflows/scrape.yml` runs once a day at 03:17 UTC (and on demand, with optional semester codes). It starts FlareSolverr as a service container, runs the parser tests, scrapes, and commits `data/` if anything changed.

## Run it locally

You need [uv](https://docs.astral.sh/uv/) and Docker.

```sh
docker run -d --name flaresolverr -p 8191:8191 flaresolverr/flaresolverr:latest
uv run python -m bzu_catalog scrape --newest 3 --out data   # or --terms 1252 1251
uv run python -m bzu_catalog parse saved-page.html --out data  # no network
uv run --group dev pytest
```

## License

[MIT](LICENSE) © Mohammad Abu-Shelbaia. The schedule data belongs to Birzeit University.
