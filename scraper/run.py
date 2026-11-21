"""Command line for collecting data and building the database.

Every step writes its files to data/raw/ and imports them into data/football.db straight away,
so the database always holds exactly what the scraper has collected. Starting from nothing:

    python -m scraper.run all            every step below in order, then assemble (hours; resumable)
    python -m scraper.run db             what's in the database, what's missing, which step makes it

Collect (every page is cached, every step resumes where it stopped):
    python -m scraper.run env            league + international scoring rates, tournaments (GitHub datasets, ~1 min)
    python -m scraper.run probe          check Wikipedia page names for each league (~2 min)
    python -m scraper.run scorers        Wikipedia top scorers + league tables, 1946 on (skips seasons already collected)
    python -m scraper.run transfermarkt  Transfermarkt open data, 2012 on: leagues, Champions League, Europa League
    python -m scraper.run elo            optional: ClubElo league strength for Europe
    python -m scraper.run continental    continental club cups: finals + top scorers
    python -m scraper.run locate         coordinates for clubs the city list can't place

Work from the database (no scraping):
    python -m scraper.run gaps           seasons with < 3 known scorers -> rows to fill in data/manual/
    python -m scraper.run assemble       sync data/football.db and build its analysis tables
    python -m scraper.run validate       compare league goals with figures in data/manual/reference_goals.csv

Debug:
    python -m scraper.run dump --title "1975–76 Bundesliga"   save a page's HTML

Options: --leagues ENG,ESP  --from 1946  --to 2025  --delay 1  --contact you@example.com  --refresh
Then:    python pipeline/build.py
"""
from __future__ import annotations

import argparse
import os
import re

from core import db
from core.paths import CACHE, RAW, ROOT
from . import clubelo, continental, environment, gaps, locate, transfermarkt, validate, wikipedia as wiki
from .assemble import assemble
from .http import PoliteSession


def session(a):
    if not a.contact:
        print("Note: SOCCER_ERAS_CONTACT isn't set. Wikimedia asks scripts to identify themselves and may\n"
              "refuse anonymous ones; if you get BLOCKED, set it to an email or GitHub URL.\n")
    return PoliteSession(CACHE / "pages", delay=a.delay, jitter=0.5, contact=a.contact)


def leagues(a, include_disabled=False):
    return wiki.load_leagues(a.leagues.split(",") if a.leagues else None, include_disabled=include_disabled)


# ---------------------------------------------------------------- steps

def step_env(a):
    print("Scoring environments and tournaments from GitHub datasets...")
    environment.build(RAW, CACHE / "datasets", a.first)


def step_probe(a):
    wiki.probe(session(a), leagues(a, include_disabled=True))


def step_scorers(a):
    wiki.collect(RAW, session(a), leagues(a), a.first, a.last, refresh=a.refresh)


def step_transfermarkt(a):
    print("Transfermarkt open data (2012 on)...")
    transfermarkt.build(RAW, CACHE / "datasets", leagues(a))


def step_elo(a):
    print("ClubElo league strength (one snapshot per season)...")
    clubelo.build(RAW, session(a), leagues(a), a.first, a.last)


def step_continental(a):
    print("Continental club competitions (finals + season top scorers)...")
    continental.build(RAW, session(a), a.first, a.last)


def step_locate(a):
    print("Locating clubs (Wikipedia coordinates, then GeoNames city names)...")
    iso2 = {lg["code"]: lg.get("iso2", "") for lg in wiki.load_leagues(include_disabled=True)}
    locate.build(RAW, CACHE, None if a.no_wiki else session(a), iso2, guess_titles=not a.no_guess)


def step_gaps(a):
    gaps.build(RAW, wiki.load_leagues(), a.first, a.last,
               only=[c.strip() for c in a.leagues.split(",")] if a.leagues else None)


def step_assemble(a):
    print("Assembling the database...")
    assemble(RAW, wiki.load_leagues(include_disabled=True))
    print("Done. Next: python pipeline/build.py")


def step_validate(a):
    validate.build(RAW)


def step_db(a):
    db.refresh(RAW)
    db.summary(RAW)


def step_dump(a):
    if not a.title:
        raise SystemExit('dump needs --title, e.g. --title "1975–76 Bundesliga"')
    # Accept "1946-47" (or a dash PowerShell mangled into "?") for "1946–47"
    title = re.sub(r"^(\d{4})\s*[-?‐-―]\s*(\d{2,4})", r"\1–\2", a.title.strip())
    html = session(a).get(wiki.page_url(title))
    if not html:
        raise SystemExit(f"No page called '{title}'.")
    out = ROOT / "debug" / (re.sub(r"[^\w–-]+", "_", title) + ".html")
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    rows = wiki.parse_scorers(html)
    print(f"Saved {out}  ({len(rows)} scorers parsed{', via ' + rows[0]['method'] if rows else ''})")


STEPS = {"env": step_env, "probe": step_probe, "scorers": step_scorers, "transfermarkt": step_transfermarkt,
         "elo": step_elo, "continental": step_continental, "locate": step_locate, "gaps": step_gaps,
         "assemble": step_assemble, "validate": step_validate, "db": step_db, "dump": step_dump}
ALL = ["env", "scorers", "transfermarkt", "elo", "continental", "locate", "assemble"]
OPTIONAL_STEPS = {"elo", "locate"}   # `all` carries on if these fail (site down)
COLLECT = {"env", "scorers", "transfermarkt", "elo", "continental", "locate"}   # import into the db when done


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=[*STEPS, "all"])
    ap.add_argument("--leagues", help="comma-separated codes, e.g. ENG,ESP (default: enabled in leagues.json)")
    ap.add_argument("--from", dest="first", type=int, default=1946)
    ap.add_argument("--to", dest="last", type=int, default=2025)
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests to a site")
    ap.add_argument("--contact", default=os.environ.get("SOCCER_ERAS_CONTACT"),
                    help="email or GitHub/project URL for the User-Agent (Wikimedia asks scripts to include one)")
    ap.add_argument("--title", help="dump: Wikipedia page title, e.g. '1975–76 Bundesliga'")
    ap.add_argument("--refresh", action="store_true", help="scorers: re-fetch seasons already collected")
    ap.add_argument("--no-wiki", action="store_true", help="locate: skip Wikipedia lookups, GeoNames only")
    ap.add_argument("--no-guess", action="store_true", help="locate: don't try club names as article titles")
    a = ap.parse_args(argv)
    RAW.mkdir(parents=True, exist_ok=True)
    for name in (ALL if a.step == "all" else [a.step]):
        try:
            STEPS[name](a)
        except SystemExit as e:
            if a.step != "all" or name not in OPTIONAL_STEPS:
                raise
            print(f"  {name} skipped: {e}")
        if name in COLLECT:
            db.refresh(RAW)          # the step's files go into data/football.db now


if __name__ == "__main__":
    main()
