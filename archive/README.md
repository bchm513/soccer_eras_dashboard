# Archive

Retired code, kept for reference. Nothing here is imported or run by the project.

| file | what it was | why it's here |
|---|---|---|
| `scraper/worldfootball.py` | scraper for worldfootball.net top-scorer pages | the site blocks scripts (HTTP 403); Wikipedia and Transfermarkt replaced it |
| `scraper/europe.py` | European Cup finals, before every confederation's cups moved into `continental.py` | only a compatibility alias by the end |
| `tests/test_worldfootball.py`, `tests/fixtures/goalgetter_esp_1955.html` | tests for the worldfootball.net parser | go with the scraper above |
| `scraper/nominatim_geocode.py` | OpenStreetMap club geocoding (`assemble --geocode`), from `scraper/clubs.py` | the `locate` step (Wikipedia, then GeoNames) replaced it; it was off by default |
| `dashboard/app.js` | the dashboard as one 600-line file | split into `dashboard/js/` modules, one per panel (November 2026) |

## Compatibility code removed in the November 2026 refactor

These read files written by older versions. If you have data from those versions, re-run the steps named.

- `scorers_worldfootball.csv` as a club source: no longer read.
- `scorers_ucl_wikipedia.csv`, `scorers_ucl_transfermarkt.csv`, `europe_finals.csv`: replaced by the `continental` and `transfermarkt` steps' files.
- A single `cup_goals` / `ucl_goals` column with one weight: replaced by one column per competition, weights in `core/competitions.py`.
- `tournament_goals` column: renamed `continental_goals`. Re-run `assemble`.
- Manual files in `data/raw/` (`club_locations_manual.csv`, `impact_manual.csv`): now moved automatically to `data/manual/` the first time any step runs.
- Reading CSVs when a database table was missing: the database is now the only source, filled by the scraper steps.
- Unused bits found in a sweep of every file: an unused `leagues_only` option in `environment.py`, an unused list of unresolved clubs in `clubs.py` (`assemble` writes the goal-sorted list), and unused imports.
- The `europe` step (now `continental`), the dashboard's `data.europe` key and the `?view=europe` link.
