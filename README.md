# Eras of the Game

Defines soccer eras by **overlapping player peaks** (1946 → today) and shows them in an interactive D3 dashboard: a map of the game's shifting hubs, a panel of career peaks, and a description of each moment. See `PLAN.md` for the full method and roadmap.

> **Currently running on SAMPLE data.** Players are fictional ("Player A1") with simulated numbers. Cities and World Cup / Euro hosts and dates are real. Drop real data into `data/raw/` and rebuild.

## Run it

```bash
pip install numpy pandas scipy scikit-learn
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
| apps, goals | appearances and goals |
| assists | blank where not recorded |
| is_star_seed | optional, ignored by the pipeline |

League baselines are computed from **all** rows in a competition-season, so include regular (non-star) players too, not just the stars.

## Layout

```
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
| hotspots.py | `HUB_RADIUS_KM` how far cities chain into one hub | 250 |
| hotspots.py | `ROLLING_SEASONS` club smoothing | 3 |
| hotspots.py | `TOURNAMENT_CAP` size vs biggest club hub | WC 1.5×, Euro 1.1× |
| hotspots.py | `FADE` post-tournament fade by month | .55, .25, .08 |
