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
- **World / Europe**: zoom presets; scroll to zoom, drag to pan.

## Getting real data

Run everything from the `soccer-eras` folder.

```bash
pip install -r requirements.txt
export SOCCER_ERAS_CONTACT="you@example.com"   # or a GitHub URL; Windows: set SOCCER_ERAS_CONTACT=...
python -m scraper.run probe          # ~1 min: checks Wikipedia page names for each league
python -m scraper.run scorers        # ~10-15 min: Wikipedia top scorers, 1946 on; resumable
python -m scraper.run transfermarkt  # one ~100 MB download: full league data, 2012 on
python -m scraper.run elo            # ~2 min: league strength from ClubElo, one snapshot per season
python -m scraper.run assemble       # builds data/raw/player_seasons.csv
python pipeline/build.py             # rebuilds the dashboard data from the real file
```

`env` (league + international scoring rates) has already been run; its files ship in `data/raw/`. Narrow a run with `--leagues ENG,ESP --from 1950 --to 1970`. Every page is cached in `data/cache/`, so a stopped run picks up where it left off.

After `assemble`, open `data/raw/unresolved_clubs.csv`: those clubs have no map location. Add them to `data/raw/club_locations_manual.csv` (`team,city,lat,lon`) and re-run `assemble`, or use `--geocode` to look them up on OpenStreetMap.

### Sources

| What | Source | Access |
|---|---|---|
| League scoring rate and games per team, by season | [jalapic/engsoccerdata](https://github.com/jalapic/engsoccerdata): ENG, ESP, ITA, FRA 1946+, NED 1956+, GER 1963+, POR/SCO/BEL 1994+ | download |
| International goals by player, international scoring rate | [martj42/international_results](https://github.com/martj42/international_results) | download |
| Club top scorers, 1946–2011 | Wikipedia league-season pages (Rank / Player / Club / Goals tables), CC BY-SA | article pages, 1 request/s |
| Club goals, assists, minutes, 2012–2025 | [Transfermarkt open dataset](https://github.com/dcaribou/transfermarkt-datasets) | download |
| League strength by season | [ClubElo](http://clubelo.com) ratings: mean Elo of each league's top-division clubs every January | API, 1 request/s |
| Club locations | `scraper/cities.csv` + your fixes + optional OpenStreetMap lookup | local |

Where two sources cover the same league-season, Transfermarkt wins. Players are linked across sources by name, so a career that spans 2012 stays one player.

### Known limitations

- **Depth varies by era.** Older Wikipedia pages list about 3 scorers; modern ones 10 or more. To keep eras comparable, every league-season is measured against the same reference group: its top 3 scorers.
- **No appearances before 2012.** Output is goals per *team* match for every source, so injury-hit seasons are under-counted.
- **Sources disagree on small details** (e.g. one goal here or there in the 1950s). Wikipedia's figure is used before 2012.
- **International goals cover competitive matches** (World Cups, continental tournaments, qualifiers); friendlies mostly lack scorer records. Puskás shows 4 of his 84. The scoring rate is measured over the same matches.
- **Internationals add to club stars but can't create one alone**, and small international samples are shrunk toward the average.
- **Leagues without a scoring rate** (Hungary, Brazil, Argentina, Germany before 1963, Netherlands before 1956, Portugal and Scotland before 1994) are left out of era-adjusted scoring until their season goal totals are added to `league_environment.csv`.
- **League strength.** Club output is scaled by the league's ClubElo rating against that season's four strongest leagues (`LEAGUE_ELO_WEIGHT`, default 0.5: a league 100 Elo below keeps ~75% of its output; the strongest are never boosted). `build.py` prints stars per league so you can see the effect. Set the weight to 0 to switch it off.
- **Goals + assists** only exists from 2012 (Transfermarkt).
- **Stars are measured against their own time.** Each player is compared with the top scorers within five seasons either side, across all leagues, leaving his own seasons out. Goals have become more concentrated among leading scorers, so an all-time comparison would make every modern striker look greater than every 1950s one.
- **A star season needs club form.** International goals add a small boost (weight 0.2) but can't carry a season alone.
- **Defaults were calibrated on the first real run** (30 stars; eras 1970–76, 1985–91, 1994–2005, 2009–19, 2021–25).
- **Name linking is conservative**: two different players sharing a name are left unlinked rather than merged, and a player spelled differently across sources stays split. Check the top stars after a run.
- **worldfootball.net blocks scripts** (HTTP 403), so it isn't used. Its scraper is kept in `scraper/worldfootball.py` for reference only.

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
  run.py           command line: env | probe | scorers | transfermarkt | assemble | all
  environment.py   league + international scoring rates from GitHub datasets
  wikipedia.py     Wikipedia top-scorer tables; leagues.json holds page-name patterns
  transfermarkt.py Transfermarkt open-data loader (2012 on)
  clubelo.py       league strength from ClubElo snapshots
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
| hotspots.py | `HUB_DIAMETER_KM` max distance between any two cities in a hub | 250 |
| hotspots.py | `ROLLING_SEASONS` club smoothing | 3 |
| hotspots.py | `TOURNAMENT_CAP` size vs biggest club hub | WC 1.5×, Euro 1.1× |
| hotspots.py | `FADE` post-tournament fade by month | .55, .25, .08 |
