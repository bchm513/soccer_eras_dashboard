# Eras of the Game

Defines soccer eras by **overlapping player peaks** (1946 → today) and shows them in an interactive D3 dashboard: a map of the game's shifting hubs, a panel of career peaks, and a description of each moment. See `PLAN.md` for the full method and roadmap.

> **The dashboard runs on SAMPLE data until you collect real data.** Sample players are fictional ("Player A1") with simulated numbers. Cities and World Cup / Euro hosts and dates are real. See **Getting real data** below.

## Run it

```bash
pip install -r requirements.txt
python pipeline/build.py          # uses data/raw/player_seasons.csv if present, else sample data
cd dashboard && python -m http.server 8000
# open http://localhost:8000
```

The dashboard needs to be served (not opened as a file) because it loads JSON. D3, TopoJSON and the world map are bundled in `dashboard/vendor/`, so it works offline.

## Controls

- **Play / pause**: button or Space. **Step**: ← / →. **Scrub**: the timeline slider.
- **Click a hub** on the map to pause and see who was playing there.
- **Click a curve** in the peaks panel to jump to that player's peak.
- **Era measure**: switch between goals (era-adjusted), goals (raw) and goals + assists to see where the eras agree.
- **Regions** (World, Europe, S. America, N. America, Asia, Africa, Oceania): zoom, and switch the peaks and era table to that region's own stars when it has enough data. Scroll to zoom, drag to pan.
- **PNG / Record**: download the map as an image, or record it as a video clip while it plays (stop with the same button).
- **Era table**: click a row to jump to that era.

## Getting real data

Run everything from the `soccer-eras` folder. Every page is cached in `data/cache/`, so any step can be stopped and re-run; it picks up where it left off.

```powershell
pip install -r requirements.txt
$env:SOCCER_ERAS_CONTACT = "you@example.com"   # or a GitHub URL (bash: export SOCCER_ERAS_CONTACT=...)
python -m scraper.run probe          # ~2 min: checks page names, league tables and leader lists for 34 leagues
python -m scraper.run scorers        # ~30-45 min: top scorers + league tables, 1946 on, every league
python -m scraper.run transfermarkt  # full league + Champions League data, 2012 on (uses the cached download)
python -m scraper.run elo            # optional: ClubElo league strength for Europe (skip if the site is down)
python -m scraper.run continental    # ~5 min: Champions League, Europa League, Libertadores, AFC, CAF, CONCACAF finals + scorers
python -m scraper.run locate         # coordinates for clubs outside the built-in city list
python -m scraper.run assemble       # builds data/raw/player_seasons.csv and league strength
python pipeline/build.py             # rebuilds the dashboard data
```

Re-running `scorers` skips every league-season already collected (add `--refresh` to fetch them again), so a second run takes minutes, not hours.

## The database: scrape once, then work from it

Everything collected lives in **`data/football.db`** (one SQLite file). Open it in [DB Browser for SQLite](https://sqlitebrowser.org), Datasette or pandas to explore.

| tables | what |
|---|---|
| `scorers_wikipedia`, `scorers_transfermarkt`, `intl_goals`, `national_elo`, ... | one per scraped file in `data/raw/` |
| `manual_*` | one per file in `data/manual/`: your own additions. **Manual data always wins.** |
| `player_seasons`, `players`, `clubs`, `moments` | built by `assemble`: every player-season, career totals, clubs with locations, major moments |

After the first scrape you never need the scraper again. The routine is:

```powershell
python -m scraper.run gaps       # lists seasons with < 3 known scorers, adds rows to fill in
#  ... edit data/manual/*.csv in Excel or any editor ...
python -m scraper.run assemble   # syncs changed files into the database and rebuilds
python pipeline/build.py
python -m scraper.run db         # shows every table and its size
```

Files in `data/manual/`:

| file | columns | use |
|---|---|---|
| `scorers_manual.csv` | competition, season, rank, player, team, goals, nationality, note | missing seasons. `gaps` pre-fills 5 rows per gap season with what's already known; fill player, team, goals and leave spare rows blank. These rows replace all other sources for that league-season, so keep the known ones. |
| `gaps.csv` | | written by `gaps`: every thin league-season. Leagues with no data at all are listed but get no rows; add them with `gaps --leagues BRA`. |
| `club_locations_manual.csv` | team, city, lat, lon | clubs with no map dot. Copy rows from `data/raw/unresolved_clubs.csv` (sorted by goals, so the top rows matter most). |
| `moments_manual.csv` | season, date, title, detail, teams, players, lat, lon, weight | your own major moments (a famous match, a transfer, a disaster). They show as diamonds on the map and in the description panel. |
| `impact_manual.csv` | season, metric, value | TV audiences or anything else; appears in the growth panel and era table. |

### Why some clubs have no location

`locate` places a club from its Wikipedia article's coordinates (or its stadium's), else from a city name inside the club name (GeoNames). It misses when a scorer table doesn't link the club (leader lists and Transfermarkt don't), when the name holds no city (Arsenal, Juventus, Ajax) and the article guess fails, or when the article has no coordinates. Unplaced clubs still count fully toward goals and eras; they only lack a map dot. Clubs are looked up most goals first, and both `locate` and `assemble` report coverage **by goals**, which is what matters for the map (the club count is dominated by small clubs with one listed scorer).

`env` (league + international scoring rates, tournament goals, tournament hosts, growth of the game, national-team strength) has already been run and its files ship in `data/raw/`. Re-run it only to refresh. Narrow any step with `--leagues BRA,ARG --from 1970 --to 1990`. Check a single page with `python -m scraper.run dump --title "1975-76 Bundesliga"`.

### Sources

| What | Source | Access |
|---|---|---|
| League scoring rate and games per team | [engsoccerdata](https://github.com/jalapic/engsoccerdata) (ENG, ESP, ITA, FRA 1946+, NED 1956+, GER 1963+, others 1994+); every other league-season from the league table on its Wikipedia page | download / article pages |
| Club top scorers, 1946–2011, 34 leagues on six continents | Wikipedia season pages; "List of ... top scorers" pages fill seasons with no table (England before 1960, early Portugal) | article pages, 1/s |
| Club goals, assists, minutes, 2012–2025 | [Transfermarkt open dataset](https://github.com/dcaribou/transfermarkt-datasets) | download |
| Internationals: goals, tournaments, hosts, growth, national Elo | [martj42/international_results](https://github.com/martj42/international_results) | download |
| Continental club competitions | Wikipedia season pages and finals lists; Transfermarkt for the Champions League and Europa League from 2012 | article pages / download |
| League strength | [ClubElo](http://clubelo.com) for Europe; elsewhere national-team Elo with a talent-exodus correction | API / computed |
| Club locations | built-in city list, then club/stadium coordinates on Wikipedia, then [GeoNames](https://www.geonames.org) city names (CC BY 4.0) | local / article pages / download |

### How the pieces fit

- **Big moments count extra.** Each player's main club season gets his tournament and cup goals, weighted in league goals:

  | competition | weight |
  |---|---|
  | World Cup | ×4 |
  | Euro, Copa América, AFCON, Asian Cup, Gold Cup | ×3 |
  | Champions League, Europa League / UEFA Cup | ×2 |
  | Libertadores, AFC and CAF Champions League, CONCACAF Champions Cup, Confederations Cup, Oceania Nations Cup | ×1 |
 Tournament goals are judged against the international scoring rate, so a World Cup goal counts the same whatever league the scorer plays in; club goals are judged against the league's rate and strength. Tournament goals leave the international row, so nothing counts twice.
- **Eras end at hand-overs.** A long run of overlapping peaks splits where the stars peaking in the four seasons before share little with those peaking in the four after.
- **League strength, worldwide.** ClubElo where available. Elsewhere the country's national-team Elo is mapped onto the club scale (fitted on European leagues when ClubElo is present), minus up to 150 Elo when the national team's goals come from players abroad. `data/raw/league_strength_world.csv` shows every number.
- **Continental titles** add weight to the winner's and runner-up's hubs, scaled by their league's strength.
- **Regions.** Each confederation with enough data gets its own stars and eras, measured against its own leagues. The dashboard's region buttons switch to them.
- **Growth of the game.** Countries appear on the map when they play their first international; hatched means playing but no league data here, solid means league data. The growth panel tracks nations, matches and leagues.
- **Impact.** The era table compares length, stars, leagues, nations active, tournaments and final attendance. To add TV audiences or anything else, create `data/raw/impact_manual.csv` with columns `season,metric,value`; it appears in the growth panel and the era table.

### Known limitations

- **Depth varies by era and league.** Older pages list about 3 scorers, some only the league leader. Every league-season is compared against its top 3.
- **No appearances before 2012.** Output is per *team* match, so injury-hit seasons are under-counted.
- **National-team strength is a proxy** for leagues without ClubElo. The exodus correction relies on linking international scorers to club rows, and before 2012 only top scorers are linked, so retention leans high then.
- **Knockout goals aren't separated** from group-stage goals at tournaments (the results data doesn't mark the stage).
- **Wikipedia page names and layouts vary.** `probe` shows what was found; fix or add page-name patterns in `scraper/leagues.json` (leagues) and `scraper/continental.py` (cups). Non-European pages are the least tested.
- **Name linking is conservative**: players with the same name aren't merged, and different spellings across sources stay split.
- **TV audiences aren't openly available**, hence the manual impact file.
- **Match-level weighting** (individual big games) is still to do; the map works at month level.
- **Moments are automatic for tournament finals and continental cup finals** only; everything else comes from `moments_manual.csv`.
- **worldfootball.net blocks scripts** (HTTP 403) and isn't used.

## Real data format

`data/raw/player_seasons.csv`, one row per player × season × competition:

| column | meaning |
|---|---|
| player_id | stable id |
| player | display name |
| season | starting year (1987 = 1987–88) |
| competition | league code (e.g. `ESP`, `ENG`) or `INT` for internationals |
| comp_type | `club` or `international` |
| club_city, lat, lon | club location (blank for international rows) |
| apps, goals | appearances (blank for scraped data) and goals |
| team_games, env_gpm | games per team and league goals per team match (environment mode) |
| assists | blank where not recorded |
| is_star_seed | optional, ignored by the pipeline |

Two modes, picked automatically. **Full-league data** (with appearances): baselines come from all rows in a competition-season, so include regular players too. **Top-scorer data** (no appearances, with `env_gpm`): output is divided by the league-season scoring rate and compared across all seasons.

## Layout

```
scraper/
  run.py           command line: env | db | gaps | probe | scorers | transfermarkt | elo | continental | locate | assemble | all
  db.py            the SQLite database (data/football.db) and manual files (data/manual/)
  gaps.py          finds thin league-seasons, prepares rows to fill in
  environment.py   league + international scoring rates from GitHub datasets
  wikipedia.py     season pages (scorers, league tables) and leader lists; leagues.json = world registry
  world.py         tournament goals, tournament hosts, growth, national Elo (from international results)
  continental.py   continental club cups: finals and top scorers
  strength.py      league strength for every league and season
  locate.py        club coordinates (Wikipedia, GeoNames)
  geo.py           country names, codes and coordinates
  transfermarkt.py Transfermarkt open-data loader (2012 on)
  clubelo.py       league strength from ClubElo snapshots
  europe.py        old name for continental.py, kept for older commands
  worldfootball.py old scraper, unused (site blocks scripts)
  http.py          polite client: robots.txt, rate limit, retries, disk cache
  clubs.py         club -> city resolver; cities.csv gazetteer
  assemble.py      joins everything into data/raw/player_seasons.csv
tests/             parser and resolver tests (python tests/test_scraper.py)
pipeline/
  build.py         runs everything -> dashboard/data/eras.json
  eras.py          era adjustment, career peak fits, overlapping-peak eras, metric agreement
  hotspots.py      density hubs (DBSCAN), rolling club weights, capped tournament spikes
  tournaments.py   real World Cup / Euro hosts and dates
  sample_data.py   synthetic dataset generator
dashboard/
  index.html, app.js, style.css, vendor/, data/eras.json
```

## Tuning knobs

| where | setting | default |
|---|---|---|
| eras.py | `FLAG_Z` star season threshold | 2.0 |
| eras.py | `MIN_FLAGGED` flagged seasons to be a star | 3 |
| eras.py | `PEAK_FRACTION` peak window cut-off | 0.7 |
| eras.py | `MIN_OVERLAP` stars overlapping for an era | 2 |
| eras.py | `SPLIT_RATIO` valley depth that splits eras | 0.7 |
| eras.py | `SHRINK_GAMES` small-sample shrinkage (real data) | 6 |
| eras.py | `REF_TOP` reference group per league-season (real data) | 3 |
| eras.py | `FLAG_Z_ENV` star season threshold (real data) | 0.75 |
| eras.py | `ERA_WINDOW` compare with top scorers within ± this many seasons (real data) | 5 |
| eras.py | `INTL_WEIGHT` international games vs club games (real data) | 0.2 |
| eras.py | `LEAGUE_ELO_WEIGHT` league-strength penalty (0 = off, 1 = full Elo odds) | 0.5 |
| eras.py | `CUP_WEIGHTS` league goals per club cup goal | UCL 2, UEL 2, others 1 |
| eras.py | `WORLD_CUP_WEIGHT` league goals per World Cup goal | 4.0 |
| eras.py | `TOURNAMENT_WEIGHT` league goals per continental championship goal | 3.0 |
| eras.py | `OTHER_TOURNAMENT_WEIGHT` Confederations Cup, Oceania Nations Cup | 1.0 |
| eras.py | `TURNOVER_MAX` / `TURNOVER_SPAN` / `TURNOVER_MIN_LEN` era hand-over split | 0.3 / 4 / 12 |
| scraper/strength.py | `EXODUS_ELO` strength lost when all national-team scorers play abroad | 150 |
| pipeline/build.py | `MIN_REGION_ROWS` club rows a confederation needs for its own stars | 150 |
| hotspots.py | `TITLE_BONUS` continental final bonus (x the season's biggest hub, then x league strength) | winner 1.0, runner-up 0.4 |
| hotspots.py | `HUB_DIAMETER_KM` max distance between any two cities in a hub | 250 |
| hotspots.py | `ROLLING_SEASONS` club smoothing | 3 |
| hotspots.py | `TOURNAMENT_CAP` size vs biggest club hub | WC 1.5×, Euro 1.1×, Copa América 1.0×, others 0.5–0.7× |
| hotspots.py | `FADE` post-tournament fade by month | .55, .25, .08 |
