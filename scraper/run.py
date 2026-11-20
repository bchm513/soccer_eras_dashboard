"""Command line for collecting real data.

    python -m scraper.run env            # league + international scoring rates (GitHub datasets, already done)
    python -m scraper.run probe          # check Wikipedia page names for each league (~1 min)
    python -m scraper.run scorers        # Wikipedia top scorers, 1946 on (~10-15 min at 1 page/s; resumable)
    python -m scraper.run transfermarkt  # Transfermarkt open data, 2012 on (one ~100 MB download)
    python -m scraper.run elo            # league strength from ClubElo, one snapshot per season (~2 min)
    python -m scraper.run continental    # Champions League, Libertadores, AFC, CAF, CONCACAF: finals + top scorers
    python -m scraper.run locate         # coordinates for clubs the city list can't place (Wikipedia + GeoNames)
    python -m scraper.run assemble       # build data/raw/player_seasons.csv
    python -m scraper.run all            # scorers -> transfermarkt -> elo -> continental -> locate -> assemble
    python -m scraper.run dump --title "1975–76 Bundesliga"   # save a page's HTML to share for debugging

Options: --leagues ENG,ESP  --from 1946  --to 2025  --delay 1  --contact you@example.com  --geocode
Then:    python pipeline/build.py
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import pandas as pd

from . import clubelo, continental, environment, locate, transfermarkt, wikipedia as wiki
from .assemble import assemble
from .http import PoliteSession

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CACHE = ROOT / "data" / "cache"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["env", "probe", "scorers", "transfermarkt", "elo", "continental", "europe", "locate", "assemble", "all", "dump"])
    ap.add_argument("--leagues", help="comma-separated codes, e.g. ENG,ESP (default: enabled in leagues.json)")
    ap.add_argument("--from", dest="first", type=int, default=1946)
    ap.add_argument("--to", dest="last", type=int, default=2025)
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests to a site")
    ap.add_argument("--contact", default=os.environ.get("SOCCER_ERAS_CONTACT"),
                    help="email or GitHub/project URL for the User-Agent (Wikimedia asks scripts to include one)")
    ap.add_argument("--title", help="dump: Wikipedia page title, e.g. '1975–76 Bundesliga'")
    ap.add_argument("--no-wiki", action="store_true", help="locate: skip Wikipedia lookups, GeoNames only")
    ap.add_argument("--geocode", action="store_true", help="look up unknown clubs on OpenStreetMap")
    a = ap.parse_args(argv)

    only = a.leagues.split(",") if a.leagues else None
    leagues = wiki.load_leagues(only)
    RAW.mkdir(parents=True, exist_ok=True)

    def session():
        if not a.contact:
            print("Note: SOCCER_ERAS_CONTACT isn't set. Wikimedia asks scripts to identify themselves and may\n"
                  "refuse anonymous ones; if you get BLOCKED, set it to an email or GitHub URL.\n")
        return PoliteSession(CACHE / "pages", delay=a.delay, jitter=0.5, contact=a.contact)

    if a.step == "env":
        print("Building scoring environments from GitHub datasets...")
        environment.build(RAW, CACHE / "datasets", a.first)

    if a.step == "dump":
        if not a.title:
            raise SystemExit('dump needs --title, e.g. --title "1975–76 Bundesliga"')
        # Accept "1946-47" (or a dash PowerShell mangled into "?") for "1946–47"
        a.title = re.sub(r"^(\d{4})\s*[-?\u2010-\u2015]\s*(\d{2,4})", r"\1–\2", a.title.strip())
        html = session().get(wiki.page_url(a.title))
        if not html:
            raise SystemExit(f"No page called '{a.title}'.")
        out = ROOT / "debug" / (re.sub(r"[^\w–-]+", "_", a.title) + ".html")
        out.parent.mkdir(exist_ok=True)
        out.write_text(html, encoding="utf-8")
        rows = wiki.parse_scorers(html)
        print(f"Saved {out}  ({len(rows)} scorers parsed{', via ' + rows[0]['method'] if rows else ''})")

    if a.step == "probe":
        wiki.probe(session(), wiki.load_leagues(only, include_disabled=True))

    if a.step in ("scorers", "all"):
        sess = session()
        out_path, env_path = RAW / "scorers_wikipedia.csv", RAW / "league_environment_wiki.csv"
        df = pd.read_csv(out_path) if out_path.exists() else pd.DataFrame()
        envdf = pd.read_csv(env_path) if env_path.exists() else pd.DataFrame()
        for lg in leagues:
            print(f"Wikipedia: {lg['name']} {max(a.first, lg.get('first', a.first))}-{min(a.last, lg.get('last', a.last))}...")
            rows, env = wiki.scrape_league(sess, lg, a.first, a.last)
            if rows:   # replace this league's rows for the scraped seasons, keep everything else
                new = pd.DataFrame(rows)
                if len(df):
                    df = df[~((df["competition"] == lg["code"]) & df["season"].isin(new["season"]))]
                df = pd.concat([df, new], ignore_index=True)
                df.to_csv(out_path, index=False)      # saved after every league
            if env:
                new = pd.DataFrame(env)
                if len(envdf):
                    envdf = envdf[~((envdf["competition"] == lg["code"]) & envdf["season"].isin(new["season"]))]
                envdf = pd.concat([envdf, new], ignore_index=True)
                envdf.to_csv(env_path, index=False)
            print(f"  {lg['code']}: {len(rows)} scorer rows, {len(env)} league tables")
        print(f"  -> {out_path}\n  -> {env_path}")

    if a.step in ("transfermarkt", "all"):
        print("Transfermarkt open data (2012 on)...")
        transfermarkt.build(RAW, CACHE / "datasets", wiki.load_leagues(only))

    if a.step in ("elo", "all"):
        print("ClubElo league strength (one snapshot per season)...")
        clubelo.build(RAW, session(), wiki.load_leagues(only), a.first, a.last)
        print(f"  -> {RAW / 'league_strength.csv'}")

    if a.step in ("continental", "europe", "all"):
        print("Continental club competitions (finals + season top scorers)...")
        continental.build(RAW, session(), a.first, a.last, comps=["UCL"] if a.step == "europe" else None)

    if a.step in ("locate", "all"):
        print("Locating clubs (Wikipedia coordinates, then GeoNames city names)...")
        iso2 = {lg["code"]: lg.get("iso2", "") for lg in wiki.load_leagues(include_disabled=True)}
        locate.build(RAW, CACHE, None if a.no_wiki else session(), iso2)

    if a.step in ("assemble", "all"):
        print("Assembling player_seasons.csv...")
        assemble(RAW, wiki.load_leagues(include_disabled=True), geocode=a.geocode, contact=a.contact)
        print("Done. Next: python pipeline/build.py")


if __name__ == "__main__":
    main()
