# Soccer Eras — Build Plan

**Goal:** define soccer eras by *players*, not calendars, from 1946 to today, and show it as an interactive dashboard: a map of the game's shifting centres of gravity, a panel of overlapping career peaks, and a description of each moment.

---

## 1. Core idea

An era is a window where **several star players are near their career peaks at the same time**. A lone great season is a spike; a true era is a plateau of overlapping peaks. Era *strength* is how many stars overlap and how high they sit together. Era *boundaries* are where one group of peaks fades and the next takes over.

Three questions the project answers:

1. **When** were the eras? (overlapping peaks over time)
2. **Where** was the heart of the game? (density hotspots of where stars played, plus tournaments)
3. **How big** was each era? (length, strength, and social impact)

---

## 2. Data

### 2.1 Coverage by metric

| Metric | Reliable from | Role |
|---|---|---|
| Goals (club + international) | ~1946 | Backbone for the full timeline |
| Appearances | ~1946 (patchy early) | Denominator for per-match rates |
| Assists | ~1990s | Sharpens modern eras |
| Shots | ~2000s (Opta era) | Sharpens modern eras |
| Attendance | ~1946 | Audience proxy before TV data |
| TV audience | ~1970s+ | Audience / impact |
| Registered players, number of leagues | sparse, by decade | Global-growth context |

All goals count — club and international — as **overall goal output**.

### 2.2 Candidate sources

- **RSSSF** (rsssf.org) — historical league tables, top scorers, international records back to the post-war years. The main source for the early decades. Mostly HTML; needs scraping.
- **worldfootball.net** — player career pages with club and international goals by season.
- **Transfermarkt datasets** (`dcaribou/transfermarkt-datasets` on GitHub/Kaggle) — modern players, clubs, appearances, goals, assists; good for 2000s onward.
- **FBref / StatsBomb open data** — shots and advanced metrics for the modern era.
- **openfootball** (GitHub) — open fixtures and results, useful for league scoring averages.
- **FIFA Big Count surveys** (2000, 2006) and confederation data — registered players.
- **Attendance:** European Football Statistics, national league archives.
- **TV audiences:** FIFA/UEFA broadcast reports for tournaments; patchy for clubs.

### 2.3 Who counts as a "star"

Avoid hand-picking. A player-season is **flagged** when its era-adjusted output is far above its league's average that season (default: z ≥ 2.5). A player is a **star** if they have at least 3 flagged seasons. This is the same idea as the NBA 30+ PPG chart, but with a cutoff that moves with each league's scoring environment.

---

## 3. Method

### 3.1 Era adjustment
For each league and season, compute the mean and standard deviation of goals per match across regular players (minimum appearances). Each player-season gets a z-score. A 30-goal season in a low-scoring league counts for more than the same tally in a high-scoring one. International goals are adjusted against the international scoring rate for that period.

### 3.2 Career peaks
Fit a smoothed curve to each star's z-scores by year (Gaussian fit, falling back to a smoothed rolling mean when the fit fails). Careers are often lopsided — fast rise, slow fade — so the plan allows a skewed curve later. Each star gets:
- **peak year** (curve maximum)
- **peak window** (years where the curve is ≥ 70% of its maximum)
- **peak height**

### 3.3 Overlapping-peak eras
For each year, count the stars inside their peak window and sum their curve heights (**era strength**). An **era** is a run of years where at least 2 stars overlap; its boundaries are where the count drops. Each era gets a length, a peak strength, its core players, and its dominant hotspot.

### 3.4 Multi-metric agreement
Run 3.1–3.3 with different output measures:
- goals only (full timeline)
- goals + assists (where available)
- goals + assists + shots-based measures (modern only)

Compare the era boundaries each one finds (year-overlap / Jaccard score). If they agree, the era is robust; where they disagree, that's a finding in itself. Also compare **raw vs era-adjusted** goals: where clusters move between the two, the scoring environment is doing the work, not the players.

### 3.5 Centre of gravity — hotspots, not averages
A plain average of club locations lands somewhere meaningless (the Alps). Instead:
1. Place every flagged player-season at its club's city.
2. Run density clustering (DBSCAN with haversine distance, ~400 km radius) to find **hubs** — e.g. a northern-Italy hub covering Turin and Milan, with Rome and Naples as separate, smaller ones.
3. Each season, a hub's **weight** is the summed era-adjusted output of the stars playing there.
4. A **3-season rolling average** gives each club hub a steady baseline.

### 3.6 Tournaments
World Cups and Euros (later Copa América etc.) add a **temporary hub** at the host location:
- Weight is **capped at 1.5×** the largest club hub at that moment, so a World Cup is the biggest circle in its month without wiping out England or Spain.
- It **fades over ~2 months** afterwards rather than vanishing.
- Later: weight by audience (TV where it exists, attendance as the stand-in for early decades).

### 3.7 Impact (to define)
Candidate dimensions, all compared relative to their own time:
- TV audiences (tournaments first)
- Attendance
- Registered players worldwide
- Number of professional leagues
- Mentions in newspaper archives

Open question: does impact help *define* an era, or is it used to *compare* eras afterwards? The pipeline keeps it as a separate layer so either is possible.

### 3.8 Granularity
Start at **season** level for player peaks and **month** level for the map. Match-level weighting (big games, finals) is a later step once match data and audience numbers are in.

---

## 4. Dashboard

Three panels on **one shared timeline** (monthly frames):

1. **Map** — hubs as circles that grow and shrink with their weight (square-root scaled). A ring marks the current top hub. Tournament hubs use a distinct dashed style. Click a hub to pause and see what was happening there.
2. **Peaks** — every star's career curve, with shaded era bands. A playhead line follows the map; players inside their peak window are highlighted. Click a curve to jump to that player's peak.
3. **Description** — the current era, the top hub, the stars near their peak, any tournament under way, plus details for a clicked hub.

Controls: play/pause, scrubber, speed, and the metric toggle (raw vs era-adjusted).

**Stack:** D3 v7, plain JS (no build step), TopoJSON world map. Data comes from one JSON file the pipeline writes. Can later move into Vue like Routelytics.

---

## 5. Project layout

```
soccer-eras/
  PLAN.md                  this file
  README.md                how to run
  pipeline/
    sample_data.py         generates the SAMPLE dataset (fictional players)
    eras.py                era adjustment, career peaks, overlapping-peak eras, metric comparison
    hotspots.py            density hubs, club weights, tournament spikes
    tournaments.py         World Cup / Euro hosts and dates (real)
    build.py               runs everything, writes dashboard/data/eras.json
  data/
    football.db            the project database (every scraped and manual table)
    raw/                   scraped files (see schema in README)
    manual/                hand-filled scorers, club locations, moments, impact series
  dashboard/
    index.html, app.js, style.css
    vendor/                D3, topojson-client, world map (offline)
    data/eras.json         pipeline output
```

---

## 6. Roadmap

| Phase | Work | Status |
|---|---|---|
| 0 | Plan, pipeline, dashboard on sample data | ✅ |
| 1 | Real data: Wikipedia top scorers 1946–2011, Transfermarkt 2012–2025, scoring rates (engsoccerdata + Wikipedia league tables), club locations | ✅ built; run locally |
| 2 | Era adjustment against each player's own time, top-3 reference group, club form required for stars | ✅ |
| 3 | Multi-metric agreement (raw vs era-adjusted vs goals + assists from 2012) | ✅ |
| 4 | League strength: ClubElo (Europe) + national-team Elo with talent-exodus correction (world) | ✅ built; ClubElo optional |
| 5 | Big moments: World Cup ×4, continental championships ×3, Champions League / Europa League ×2, other club cups and minor tournaments ×1; continental titles on the map scaled by strength | ✅ |
| 6 | Eras split at hand-overs between groups of stars | ✅ |
| 7 | World expansion: 34 leagues on six continents, five continental cups, 156 tournaments, regional stars and eras | ✅ built; page names for non-European leagues need a `probe` run |
| 8 | Growth of the game: countries fade in at first international, no-data shading, growth panel | ✅ |
| 9 | Impact: era comparison table (length, stars, leagues, nations active, tournaments, final crowds) + manual series hook for TV audiences | ✅ (TV data must be added by hand) |
| 10 | Postable: PNG export and video clip recording of the map, deep links | ✅ |
| 11 | Project database (data/football.db): scrape once, fill gaps and add moments by hand in data/manual/, manual data wins | ✅ |
| 12 | Moments: tournament and continental finals as map diamonds and description entries; manual moments file | ✅ first pass |
| 13 | From dashboard to a representation of football: player, club and moment pages built from the database; story-led walkthroughs of major years | To do |
| 14 | Match-level weighting for individual big games | To do |
| 15 | Knockout-round weighting at tournaments (needs stage data) | To do |
| 16 | Host as a public website | To do |

Real run with the new weights (Nov 2026): 34 stars; eras 1948–52, 1956–58, 1960–65, 1968–71, 1982–90, 1992–99, 2001–11, 2012–25.

First real run (8 European leagues, World Cup and continental championship goals): eras 1948–52, 1956–65, 1968–71, 1983–90, 1991–99, 2001–06, 2007–11, 2012–25.

## 7. Open questions

- How to weight club vs international goals against each other.
- Whether South American and other non-European leagues get equal treatment early (data quality differs).
- Exact star threshold (z cutoff, minimum flagged seasons) — test sensitivity.
- Definition of impact, and whether it defines or compares eras.
- Whether to model skewed career curves instead of symmetric ones.
