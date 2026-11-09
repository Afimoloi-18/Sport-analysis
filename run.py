"""Daily run: settle yesterday's picks, find today's fixtures, apply the rulebook, publish."""
import json
import os
import sys
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from engine import ledger, notify, report, rules
from engine.api import Api, ApiError, BudgetExceeded, PlanError
from engine.data import Filter, fetch_league_seasons, fetch_team_previous, finished, load_league_types, norm


def main():
    with open("config.json") as fh:
        cfg = json.load(fh)
    tz = cfg["timezone"]
    day = os.environ.get("RUN_DATE") or datetime.now(ZoneInfo(tz)).date().isoformat()
    notes, lines = [], []

    def log(msg):
        print(msg, flush=True)
        lines.append(msg)

    picks, cuts, checked, excluded = [], [], 0, 0
    rows = ledger.read()
    key = os.environ.get("API_FOOTBALL_KEY")

    if not key:
        notes.append("No API key found. Add the API_FOOTBALL_KEY secret in the repo settings.")
    else:
        api = Api(key, cfg["max_api_calls"], cfg["min_seconds_between_calls"])
        try:
            rows = ledger.settle(api, rows, log)
            league_types = load_league_types(api, log)
            filt = Filter(cfg, league_types)

            todays = [norm(x) for x in api.get("/fixtures", date=day, timezone=tz)]
            upcoming = [f for f in todays if f["status"] == "NS"]
            eligible = [f for f in upcoming if filt.game_ok(f)]
            excluded = len(upcoming) - len(eligible)
            log(f"{len(todays)} fixtures today, {len(upcoming)} not started, {len(eligible)} in men's pro leagues")

            groups = {}
            for f in eligible:
                groups.setdefault((f["league_id"], f["season"]), []).append(f)
            order = sorted(groups.items(), key=lambda kv: -len(kv[1]))  # most fixtures per call first

            league_games, skipped = {}, 0
            for (lid, season), fx in order:
                if api.left() < 2:
                    skipped += len(fx)
                    continue
                try:
                    games = finished(fetch_league_seasons(api, lid, season))
                    league_games[lid] = [g for g in games if filt.teams_ok(g["home"], g["away"])]
                except PlanError:
                    raise
                except ApiError as ex:
                    log(f"League {lid} failed: {ex}")
                    skipped += len(fx)

            # Promoted/relegated teams: top up last season's games from their old league.
            extras = {}
            ready = [f for f in eligible if f["league_id"] in league_games]
            for f in ready:
                pool = league_games[f["league_id"]]
                for tid in (f["home_id"], f["away_id"]):
                    if tid in extras or api.left() < 1:
                        continue
                    if len(rules.last_games(pool, tid, f["date"], cfg["rules"]["common_last_n"])) < cfg["rules"]["common_last_n"]:
                        try:
                            extras[tid] = [g for g in finished(fetch_team_previous(api, tid, f["season"])) if filt.game_ok(g)]
                        except PlanError:
                            raise
                        except ApiError as ex:
                            log(f"Team {tid} history failed: {ex}")
                            extras[tid] = []

            for f in ready:
                merged = {g["id"]: g for g in league_games[f["league_id"]]}
                for tid in (f["home_id"], f["away_id"]):
                    for g in extras.get(tid, []):
                        merged[g["id"]] = g
                ev = rules.evaluate(f, list(merged.values()), cfg["rules"])
                checked += 1
                (picks if ev["verdict"] else cuts).append({"fixture": f, "eval": ev})

            if skipped:
                notes.append(f"{skipped} matches not checked: daily data allowance reached. Biggest leagues were checked first.")
        except PlanError as ex:
            notes.append(f"The data provider refused the request: {ex}. The free plan may not cover this; see README.")
        except BudgetExceeded as ex:
            notes.append(f"Stopped early: {ex}.")
        except ApiError as ex:
            notes.append(f"Data error: {ex}")
        log(f"API calls used: {api.calls}" + (f", provider says {api.remaining} left today" if api.remaining is not None else ""))

    picks.sort(key=rules.rank_key)
    cuts.sort(key=lambda c: c["fixture"]["date"])
    rows = ledger.add_picks(rows, picks, day)
    ledger.write(rows)
    st = ledger.stats(rows)

    os.makedirs("data/picks", exist_ok=True)
    with open(f"data/picks/{day}.json", "w") as fh:
        json.dump({"day": day, "picks": picks, "cuts": cuts, "notes": notes, "log": lines}, fh, indent=1, default=str)

    summary = [f"{len(picks)} picks", f"{checked} matches checked", f"{excluded} excluded (women, youth, cups, reserves)"]
    recent = sorted(rows, key=lambda r: r["kickoff"], reverse=True)[:30]
    html = report.render(day, tz, picks, cuts, st, recent, notes, summary)
    os.makedirs("docs/archive", exist_ok=True)
    for path in ("docs/index.html", f"docs/archive/{day}.html"):
        with open(path, "w") as fh:
            fh.write(html)
    open("docs/.nojekyll", "w").close()

    notify.send(telegram_text(day, tz, picks, st, notes, checked), log)
    return 0


def page_url():
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        return ""
    owner, name = repo.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}/"


def telegram_text(day, tz, picks, st, notes, checked):
    d = datetime.fromisoformat(day).strftime("%a %d %b")
    out = [f"<b>⚽ Shortlist {d}</b>"]
    if picks:
        for i, p in enumerate(picks, 1):
            f, ev = p["fixture"], p["eval"]
            ko = datetime.fromisoformat(f["date"]).astimezone(ZoneInfo(tz)).strftime("%H:%M")
            h, a = escape(f["home"]), escape(f["away"])
            if ev["backed"] == "home":
                h = f"<b>{h}</b>"
            else:
                a = f"<b>{a}</b>"
            out.append(f'{i}. <b>{ev["verdict"]}</b> · {h} v {a} · {ko} · {escape(f["country"])} ({ev[ev["backed"]]["score"]}/3)')
    else:
        out.append(f"No match passed the rules today ({checked} checked).")
    a = st["all"]
    if a["settled"]:
        out.append(f'\nTrack record: {a["won"]}/{a["settled"]} ({a["pct"]}%) · home {st["home"]["won"]}/{st["home"]["settled"]} · away {st["away"]["won"]}/{st["away"]["settled"]}')
    for n in notes:
        out.append(f"⚠️ {escape(n)}")
    url = page_url()
    if url:
        out.append(f'\n<a href="{url}">Full report with the evidence</a>')
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main())
