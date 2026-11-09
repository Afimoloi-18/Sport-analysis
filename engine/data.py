"""Fetching + normalising API-Football data, league filtering, caching."""
import json
import os
import re
import time
from datetime import datetime, timezone

from .api import ApiError, BudgetExceeded, PlanError

FINISHED = {"FT", "AET", "PEN"}
DATA_DIR = "data"
LEAGUES_CACHE = os.path.join(DATA_DIR, "leagues_cache.json")


def utc_iso(s):
    """All dates stored as UTC ISO strings so they compare correctly as text."""
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()


def norm(item):
    f, lg, t, g = item["fixture"], item["league"], item["teams"], item["goals"]
    return {
        "id": f["id"],
        "date": utc_iso(f["date"]),
        "status": f["status"]["short"],
        "season": lg.get("season"),
        "league_id": lg["id"],
        "league": lg.get("name", ""),
        "country": lg.get("country", ""),
        "home_id": t["home"]["id"],
        "away_id": t["away"]["id"],
        "home": t["home"]["name"],
        "away": t["away"]["name"],
        "hg": g["home"],
        "ag": g["away"],
    }


def finished(games):
    return [g for g in games if g["status"] in FINISHED and g["hg"] is not None and g["ag"] is not None]


class Filter:
    def __init__(self, cfg, league_types):
        self.league_types = league_types  # id(str) -> {"type","name","country"}
        self.lp = [re.compile(p, re.I) for p in cfg["exclude_league_name_patterns"]]
        self.tp = [re.compile(p, re.I) for p in cfg["exclude_team_name_patterns"]]
        self.ex_ids = set(cfg.get("exclude_league_ids") or [])
        self.only = set(cfg.get("include_only_league_ids") or [])

    def league_ok(self, league_id, name):
        if league_id in self.ex_ids:
            return False
        if self.only and league_id not in self.only:
            return False
        info = self.league_types.get(str(league_id))
        if not info or info.get("type") != "League":
            return False
        return not any(p.search(name or info.get("name", "")) for p in self.lp)

    def teams_ok(self, home, away):
        return not any(p.search(home) or p.search(away) for p in self.tp)

    def game_ok(self, g):
        return self.league_ok(g["league_id"], g["league"]) and self.teams_ok(g["home"], g["away"])


def load_league_types(api, log):
    """League id -> type (League/Cup). Cached for 7 days (1 API call to refresh)."""
    if os.path.exists(LEAGUES_CACHE):
        with open(LEAGUES_CACHE) as fh:
            cache = json.load(fh)
        if time.time() - cache.get("fetched", 0) < 7 * 86400 and cache.get("leagues"):
            return cache["leagues"]
    resp = api.get("/leagues")
    leagues = {
        str(x["league"]["id"]): {"type": x["league"]["type"], "name": x["league"]["name"], "country": x["country"]["name"]}
        for x in resp
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LEAGUES_CACHE, "w") as fh:
        json.dump({"fetched": time.time(), "leagues": leagues}, fh)
    log(f"League list refreshed: {len(leagues)} competitions")
    return leagues


def fetch_league_seasons(api, league_id, season):
    """Current + previous season of one league: everything the rules need for all its teams."""
    games = []
    for s in (season, season - 1):
        resp = api.get("/fixtures", league=league_id, season=s)
        games += [norm(x) for x in resp]
    return games


def fetch_team_previous(api, team_id, season):
    """For promoted/relegated teams: their games from last season in whatever league they were in."""
    return [norm(x) for x in api.get("/fixtures", team=team_id, season=season - 1)]


__all__ = [
    "ApiError", "BudgetExceeded", "PlanError", "norm", "finished", "Filter",
    "load_league_types", "fetch_league_seasons", "fetch_team_previous",
]
