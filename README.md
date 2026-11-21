# Eras of the Game

Defines soccer eras by **overlapping player peaks** (1946 → today) and shows where the game's heart was at each moment: a map of shifting hubs, the career peaks of the stars who shaped each era, the moments people remember, and how the game grew. See `PLAN.md` for the method and roadmap.

Everything is built by the scraper from public sources. Nothing needs to be supplied by hand, so anyone with this folder can rebuild the whole project.

## Quick start

```bash
pip install -r requirements.txt
python pipeline/build.py                 # no data yet -> builds the SAMPLE dashboard (fictional players)
python serve.py                          # opens http://localhost:8000 in your default browser
```

If you have scraped data in `data/raw/` but no database yet, `build.py` stops and tells you to run `python -m scraper.run assemble` first; it only builds the sample when there's no scraped data at all (or with `--sample`).

The dashboard has to be served (not opened as a file). D3, TopoJSON and the world map are bundled in `dashboard/vendor/`, so it works offline.

## Building the real data

```bash
export SOCCER_ERAS_CONTACT="you@example.com"   # PowerShell: $env:SOCCER_ERAS_CONTACT = "..."
python -m scraper.run all       # every step in order; a few hours the first time (1 page/second)
python pipeline/build.py
```

The contact is put in the request header because Wikimedia asks scripts to identify themselves. It isn't sent anywhere else.

`all` runs these steps, which can also be run one at a time:

| step | what it collects | time |
|---|---|---|
| `env` | league and international scoring rates, tournament goals, hosts and finals, growth of the game, national-team Elo (GitHub datasets) | ~1 min |
| `scorers` | top scorers and league tables from Wikipedia season pages, 34 leagues, 1946 on | hours the first time |
| `transfermarkt` | full league, Champions League and Europa League scoring, 2012 on (one ~100 MB download) | minutes |
| `elo` | optional: ClubElo league strength for Europe (skipped if the site is down) | ~2 min |
| `continental` | continental club cups: finals and top scorers | ~5 min |
| `locate` | map coordinates for clubs (Wikipedia, then GeoNames) | ~20 min |
| `assemble` | the analysis tables: player-seasons, players, clubs, finals, moments, league strength | ~1 min |

Every downloaded page is cached in `data/cache/`, so any step can be stopped and restarted. `scorers` skips seasons it already has (add `--refresh` to fetch them again). Narrow any step with `--leagues BRA,ARG --from 1970 --to 1990`. Check a single page with `python -m scraper.run dump --title "1975–76 Bundesliga"`.

## The database

**The scraper is the only thing that writes to `data/football.db`.** Each step saves its files in `data/raw/` and imports them into the database as soon as it finishes. `assemble` then builds the analysis tables, and the pipeline reads only the database. To see what's there and what's missing:

```bash
python -m scraper.run db
```

This lists every table, its row count and the step that made it, then gives the commands for anything still missing. Open the file in [DB Browser for SQLite](https://sqlitebrowser.org), Datasette or pandas to explore it.

The database, `data/raw/` and `data/cache/` are rebuilt by the scraper and aren't shared (see `.gitignore`). `data/manual/` is shared.

### Your additions: `data/manual/`

Hand-made fixes live in `data/manual/`, are imported as `manual_*` tables, and **always win over scraped data**. They're meant to be shared, so one person's fixes help everyone.

| file | columns | use |
|---|---|---|
| `scorers_manual.csv` | competition, season, rank, player, team, goals, nationality, note | seasons the scraper couldn't find. `python -m scraper.run gaps` adds 5 rows per thin season, pre-filled with what's known; fill player, team and goals and leave spare rows blank. These rows replace all other sources for that league-season, so keep the known ones. |
| `gaps.csv` | | written by `gaps`: every league-season with fewer than 3 scorers. Leagues with no data at all are listed but get no rows; add them with `gaps --leagues BRA`. |
| `club_locations_manual.csv` | team, city, lat, lon | clubs with no map dot. Copy rows from `data/raw/unresolved_clubs.csv`, which is sorted by goals. |
| `moments_manual.csv` | season, date, title, detail, teams, players, lat, lon, weight | your own major moments (a famous match, a transfer, a disaster); diamonds on the map and entries in the description panel. |
| `impact_manual.csv` | season, metric, value | TV audiences or other impact series; shown in the growth panel and era table. |

After editing: `python -m scraper.run assemble`, then `python pipeline/build.py`.

### Checking the goal figures

Add figures you look up (Wikipedia, RSSSF, league sites) to `data/manual/reference_goals.csv`, then run `python -m scraper.run validate`:

```
player,competition,season,goals,source
Lionel Messi,ESP,2011,50,Wikipedia            <- one season (2011 = 2011–12): should match exactly
Lionel Messi,ESP,,474,Guinness World Records  <- blank season: a career total in that league
```

Career totals before 2012 come out lower than the published figure, because the scraper only has each season's top scorers. The report lists the seasons it has, the gaps, and how many goals the missing seasons must hold. A database total *higher* than the reference is worth a look (a name clash or a duplicate). Results also go to `data/raw/validation.csv`.

## How it works

- **Era-adjusted goals.** Each club season is compared with the top 3 scorers of nearby seasons (±5) in leagues of its time, adjusted for the league's scoring rate and strength. A player's own seasons are left out of his comparison group.
- **Big moments count extra**, as league goals per goal. All weights are set in `core/competitions.py`:

  | competition | weight |
  |---|---|
  | World Cup | ×4 |
  | Euro, Copa América, AFCON, Asian Cup, Gold Cup | ×3 |
  | Champions League, Europa League / UEFA Cup | ×2 |
  | Libertadores, AFC and CAF Champions League, CONCACAF Champions Cup, Confederations Cup, Oceania Nations Cup | ×1 |

  Tournament goals are judged against the international scoring rate, so a World Cup goal counts the same whatever league the scorer plays in. They move off the player's international row onto his main club season, so nothing counts twice.
- **Stars and eras.** A star has at least 3 seasons well above the top scorers of his time. His peak window comes from a curve fitted to his career, kept inside the seasons he actually played and at most 5 seasons either side of the peak. An era is a run of seasons with at least 2 stars at their peak. Eras split where strength dips into a valley, or where one group of stars hands over to the next. The hand-over test weighs each star by how close to his peak he is, so a fading star doesn't tie his era to the next one.
- **League strength, worldwide.** ClubElo where available. Elsewhere the national team's Elo, mapped onto the club scale, minus up to 150 Elo when the national team's scorers play abroad.
- **The map.** Hubs are clusters of cities where stars played, sized by their output (3-season rolling). Continental titles add weight to the finalists' hubs. Tournaments appear as capped, fading circles at the host. Countries fade in when they play their first international.
- **Moments.** Every tournament final and continental club final, plus your own, as diamonds on the map and entries in the description panel.
- **Regions.** Each confederation with enough data gets its own stars and eras. The region buttons switch to them.

### Known limitations

- **Depth varies by era and league.** Older pages list about 3 scorers, some only the league leader. Every league-season is compared against its top 3.
- **No appearances before 2012.** Output is per *team* match, so injury-hit seasons are under-counted.
- **National-team strength is a proxy** for leagues without ClubElo.
- **Knockout goals aren't separated** from group-stage goals at tournaments.
- **Wikipedia page names vary.** `probe` shows what was found; fix page-name patterns in `scraper/leagues.json` (leagues) and `scraper/continental.py` (cups).
- **Name linking is conservative**: players with the same name aren't merged, and different spellings across sources stay split.
- **TV audiences aren't openly available**, hence the manual impact file.

## Layout

```
core/                shared by the scraper and the pipeline
  paths.py           where everything lives
  competitions.py    every competition: names, weights, map sizes (edit weights here)
  db.py              the database: import, load, status
  geo.py             country names, codes, coordinates
  common.py          name normalising, seasons
scraper/             collecting data and building the database
  run.py             the command line: one function per step
  environment.py     scoring rates and international data (GitHub datasets)
  world.py           tournament goals and hosts, growth, national Elo
  wikipedia.py       season pages, league tables, leader lists; leagues.json = league registry
  transfermarkt.py   Transfermarkt open data (2012 on)
  continental.py     continental club cups: finals and top scorers
  clubelo.py         ClubElo league strength
  locate.py          club coordinates (Wikipedia, GeoNames)
  clubs.py           club -> city resolver; cities.csv gazetteer
  assemble.py        builds the analysis tables, using:
    linking.py         club rows from every source, one id per player, cup goals
    internationals.py  international rows; tournament goals to club rows
    strength.py        league strength for every league and season
    moments.py         tournament finals, club finals, your moments
  gaps.py            thin league-seasons -> rows to fill in
  validate.py        compares league goals with figures you look up
  http.py            polite client: robots.txt, rate limit, retries, page cache
pipeline/            analysis: database -> dashboard/data/eras.json
  build.py           runs everything
  eras.py            era adjustment, career peaks, overlapping-peak eras, metric agreement
  hotspots.py        hubs, club weights, tournament circles
  tournaments.py     World Cup and Euro hosts and dates
  sample_data.py     synthetic dataset for the sample dashboard
dashboard/
  index.html, style.css, vendor/, data/eras.json
  js/main.js         loads the data, shared state, the clock
  js/map.js, peaks.js, panel.js, growth.js, table.js, export.js, time.js, tip.js
serve.py             serves the dashboard and opens it in your browser
tests/               python -m pytest tests
archive/             retired code, kept for reference (see archive/README.md)
```

## Tuning knobs

| where | setting | default |
|---|---|---|
| core/competitions.py | every competition's weight, map size and moment order | see the table above |
| pipeline/eras.py | `FLAG_Z_ENV` star season threshold | 0.75 |
| pipeline/eras.py | `MIN_FLAGGED` flagged seasons to be a star | 3 |
| pipeline/eras.py | `PEAK_FRACTION` peak window cut-off | 0.7 |
| pipeline/eras.py | `MIN_OVERLAP` stars overlapping for an era | 2 |
| pipeline/eras.py | `SPLIT_RATIO` valley depth that splits eras | 0.7 |
| pipeline/eras.py | `MAX_PEAK_HALF` a peak window reaches at most this many seasons either side of the peak (and never past the career) | 5 |
| pipeline/eras.py | `TURNOVER_MAX` / `TURNOVER_SPAN` / `TURNOVER_MIN_LEN` era hand-over split (overlap weighted by how near each star is to his peak) | 0.3 / 4 / 12 |
| pipeline/eras.py | `REF_TOP` / `ERA_WINDOW` comparison group | top 3, ±5 seasons |
| pipeline/eras.py | `INTL_WEIGHT` international games vs club games | 0.2 |
| pipeline/eras.py | `LEAGUE_ELO_WEIGHT` league-strength penalty (0 = off, 1 = full Elo odds) | 0.5 |
| pipeline/eras.py | `SHRINK_GAMES` small-sample shrinkage | 6 |
| scraper/strength.py | `EXODUS_ELO` strength lost when all national-team scorers play abroad | 150 |
| pipeline/build.py | `MIN_REGION_ROWS` club rows a confederation needs for its own stars | 150 |
| pipeline/hotspots.py | `TITLE_BONUS` continental final bonus (× biggest hub × league strength) | winner 1.0, runner-up 0.4 |
| pipeline/hotspots.py | `HUB_DIAMETER_KM` max distance between cities in a hub | 250 |
| pipeline/hotspots.py | `ROLLING_SEASONS` / `FADE` club smoothing, tournament fade | 3 / .55, .25, .08 |

## Controls

- **Play / pause**: button or Space. **Step**: ← / →. **Scrub**: the timeline slider.
- **Click a hub** to pause and see who was playing there. **Click a curve** to jump to that player's peak.
- **Era measure**: goals (era-adjusted), goals (raw), goals + assists.
- **Regions**: zoom, and switch the peaks and era table to that region's own stars. Scroll to zoom, drag to pan.
- **PNG / Record**: download the map as an image, or record a video clip while it plays.
- **Deep links**: `?t=2016-05&view=UEFA&metric=goals_raw&hub=hub7`.
