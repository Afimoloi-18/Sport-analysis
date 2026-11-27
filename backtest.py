"""Backtest: apply the rulebook to finished matches of past days and measure what actually happened.

Every match is judged only on games played BEFORE its kick-off, exactly like the live run.
Output: data/backtest.json and docs/backtest.html, plus a short Telegram summary.
"""
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from html import escape as e
from zoneinfo import ZoneInfo

from engine import notify, rules
from engine.api import Api, ApiError, BudgetExceeded, PlanError
from engine.data import Filter, fetch_league_seasons, fetch_red_cards, finished, load_league_types, norm


def res(hg, ag):
    return "H" if hg > ag else "A" if ag > hg else "D"


def hit(bet, r):
    return {"1": r == "H", "1X": r in "HD", "X2": r in "AD", "2": r == "A"}[bet]


def main():
    cfg = json.load(open("config.json"))
    R = cfg["rules"]
    tz = cfg["timezone"]
    days_back = int(os.environ.get("BACKTEST_DAYS") or 14)
    end = date.fromisoformat(os.environ.get("RUN_DATE") or datetime.now(ZoneInfo(tz)).date().isoformat())
    api = Api(os.environ["API_FOOTBALL_KEY"], int(os.environ.get("BACKTEST_MAX_CALLS") or 3000), cfg["min_seconds_between_calls"])
    filt = Filter(cfg, load_league_types(api, print))

    matches, league_games, notes = [], {}, []
    try:
        for i in range(days_back, 0, -1):
            d = (end - timedelta(days=i)).isoformat()
            fx = [norm(x) for x in api.get("/fixtures", date=d, timezone=tz)]
            done = [f for f in fx if f["status"] == "FT" and filt.game_ok(f)]
            for f in done:
                lid = f["league_id"]
                if lid not in league_games:
                    try:
                        league_games[lid] = [g for g in finished(fetch_league_seasons(api, lid, f["season"]))
                                             if filt.teams_ok(g["home"], g["away"])]
                    except PlanError:
                        raise
                    except ApiError as ex:
                        league_games[lid] = None
                        print("league fail", lid, ex)
                if not league_games[lid]:
                    continue
                ev = rules.evaluate(f, league_games[lid], R)
                matches.append({"day": d, "f": f, "ev": ev, "r": res(f["hg"], f["ag"])})
            print(d, len(done), "matches, calls so far", api.calls, flush=True)
    except (BudgetExceeded, PlanError, ApiError) as ex:
        notes.append(f"Stopped early: {ex}")

    voided = 0
    try:
        reds = fetch_red_cards(api, [m["f"]["id"] for m in matches])
        kept = [m for m in matches if not reds.get(m["f"]["id"])]
        voided = len(matches) - len(kept)
        matches = kept
    except (BudgetExceeded, PlanError, ApiError) as ex:
        notes.append(f"Red-card check incomplete: {ex}")

    out = analyse(matches)
    out["red_void"] = voided
    out.update({"days": days_back, "end": end.isoformat(), "notes": notes, "calls": api.calls})
    os.makedirs("data", exist_ok=True)
    json.dump(out, open("data/backtest.json", "w"), indent=1)
    os.makedirs("docs", exist_ok=True)
    open("docs/backtest.html", "w").write(render(out))
    a = out["picks"]["all"]
    notify.send(
        f"<b>Backtest, last {days_back} days</b>\n{out['n']} matches checked, {a['n']} would have been picks, "
        f"{a['pct']}% won. Picks a day: avg {out['per_day_summary']['avg']}, "
        f"min {out['per_day_summary']['min']}, {out['per_day_summary']['days_under_12']} days under 12.\nFull breakdown: {page_url()}backtest.html", print)


def page_url():
    repo = os.environ.get("GITHUB_REPOSITORY", "/")
    owner, name = repo.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}/"


def rate(items):
    n = len(items)
    w = sum(1 for x in items if x)
    return {"n": n, "won": w, "pct": round(100 * w / n) if n else None}


def analyse(M):
    o = {"n": len(M)}
    picks = [m for m in M if m["ev"]["verdict"]]
    o["picks"] = {"all": rate([hit(m["ev"]["verdict"], m["r"]) for m in picks])}
    for v in ("1", "1X", "X2"):
        o["picks"][v] = rate([hit(v, m["r"]) for m in picks if m["ev"]["verdict"] == v])

    # baselines: what you'd get betting blindly
    o["base"] = {
        "home win (1)": rate([m["r"] == "H" for m in M]),
        "home or draw (1X)": rate([m["r"] in "HD" for m in M]),
        "away or draw (X2)": rate([m["r"] in "AD" for m in M]),
    }

    # side-level table: every team's rule results vs whether that side avoided defeat / won
    sides = []
    for m in M:
        for s in ("home", "away"):
            S = m["ev"][s]
            won = m["r"] == ("H" if s == "home" else "A")
            no_loss = won or m["r"] == "D"
            sides.append({"side": s, "S": S, "won": won, "nl": no_loss})
    o["sides"] = sides_summary(sides)

    # cut groups: would they have landed?
    def grp(name, cond, bet):
        sel = [m for m in M if cond(m)]
        o.setdefault("cuts", {})[name] = {"bet": bet, **rate([hit(bet, m["r"]) for m in sel])}

    H = lambda m: m["ev"]["home"]
    A = lambda m: m["ev"]["away"]
    grp("Away 2/3 + gate (cut by away downgrade)", lambda m: A(m)["gate"]["pass"] and A(m)["score"] == 2 and not m["ev"]["verdict"], "X2")
    grp("Home 3/3 but gate fail", lambda m: not H(m)["gate"]["pass"] and H(m)["score"] == 3 and H(m)["gate"]["games"] >= 5, "1")
    grp("Home 2/3 but gate fail", lambda m: not H(m)["gate"]["pass"] and H(m)["score"] == 2 and H(m)["gate"]["games"] >= 5, "1X")
    grp("Home 1/3 + gate", lambda m: H(m)["gate"]["pass"] and H(m)["score"] == 1, "1X")
    grp("Away 3/3 as straight away win", lambda m: A(m)["gate"]["pass"] and A(m)["score"] == 3, "2")
    grp("Conflict (both sides 2+)", lambda m: m["ev"]["reason"].startswith("Conflict"), "1X")

    # gate thresholds on current picks' logic
    o["gate"] = {}
    for g in (6, 7, 8, 9, 10, 12):
        sel = [m for m in M if m["ev"]["home"]["gate"]["games"] >= 5 and m["ev"]["home"]["gate"]["goals"] >= g and m["ev"]["home"]["score"] >= 2]
        o["gate"][g] = {"home 2+/3 as 1X": rate([hit("1X", m["r"]) for m in sel]),
                        "home 3/3 as 1": rate([hit("1", m["r"]) for m in sel if m["ev"]["home"]["score"] == 3])}

    # picks per day: do we have enough for 4 tickets x 3 legs?
    days = sorted({m["day"] for m in M})
    per = {d: sum(1 for m in picks if m["day"] == d) for d in days}
    o["per_day"] = per
    o["per_day_summary"] = {"min": min(per.values()) if per else 0, "max": max(per.values()) if per else 0,
                            "avg": round(sum(per.values()) / len(per), 1) if per else 0,
                            "days_under_12": sum(1 for v in per.values() if v < 12)}

    # which leagues/countries produced picks and how they did
    by = defaultdict(list)
    for m in picks:
        by[m["f"]["country"]].append(hit(m["ev"]["verdict"], m["r"]))
    o["countries"] = sorted(([k, rate(v)] for k, v in by.items()), key=lambda kv: -kv[1]["n"])[:25]
    o["pick_list"] = [
        {"day": m["day"], "home": m["f"]["home"], "away": m["f"]["away"], "country": m["f"]["country"],
         "league": m["f"]["league"], "bet": m["ev"]["verdict"], "score": f'{m["f"]["hg"]}-{m["f"]["ag"]}',
         "won": hit(m["ev"]["verdict"], m["r"])}
        for m in sorted(picks, key=lambda m: m["day"])
    ]
    return o


def sides_summary(sides):
    out = {}
    for name, key in (("Common opponents (R1)", "r1"), ("Head to head (R2)", "r2"), ("Form (R3)", "r3")):
        for flag in (True, False):
            for where in ("home", "away"):
                sel = [x for x in sides if x["side"] == where and x["S"]["gate"]["pass"] and x["S"][key] == flag]
                out[f"{name} {'pass' if flag else 'fail'} · {where}"] = {"won": rate([x["won"] for x in sel]),
                                                                          "no_loss": rate([x["nl"] for x in sel])}
    return out


def render(o):
    def pct(r):
        return "–" if r["pct"] is None else f'{r["pct"]}% <span class="n">({r["won"]}/{r["n"]})</span>'

    rows = lambda d: "".join(f"<tr><td>{e(str(k))}</td><td>{pct(v)}</td></tr>" for k, v in d.items())
    picks = "".join(f"<tr><td>{e(k)}</td><td>{pct(v)}</td></tr>" for k, v in o["picks"].items())
    cuts = "".join(f'<tr><td>{e(k)}</td><td>{e(v["bet"])}</td><td>{pct(v)}</td></tr>' for k, v in o["cuts"].items())
    sides = "".join(f'<tr><td>{e(k)}</td><td>{pct(v["won"])}</td><td>{pct(v["no_loss"])}</td></tr>' for k, v in o["sides"].items())
    gate = "".join(f'<tr><td>{g}+ goals</td><td>{pct(v["home 3/3 as 1"])}</td><td>{pct(v["home 2+/3 as 1X"])}</td></tr>' for g, v in o["gate"].items())
    ctry = "".join(f"<tr><td>{e(k)}</td><td>{pct(v)}</td></tr>" for k, v in o["countries"])
    plist = "".join(f'<tr><td>{e(p["day"][5:])}</td><td>{e(p["home"])} v {e(p["away"])}<span class="sub">{e(p["country"])} · {e(p["league"])}</span></td><td>{e(p["bet"])}</td><td>{e(p["score"])}</td><td class="{"w" if p["won"] else "l"}">{"won" if p["won"] else "lost"}</td></tr>' for p in o["pick_list"])
    notes = "".join(f'<p class="note">{e(n)}</p>' for n in o["notes"])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Model Backtest</title><style>
:root{{--bg:#f6f5f1;--card:#fff;--ink:#1b1d1f;--muted:#6b7075;--line:#e3e1da;--ok:#1d7a46;--no:#a23b2c}}
@media (prefers-color-scheme:dark){{:root{{--bg:#121416;--card:#1b1e21;--ink:#ecebe6;--muted:#9aa0a6;--line:#2c3034;--ok:#5fcf8c;--no:#f08a78}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,Segoe UI,Roboto,sans-serif}}
main{{max-width:760px;margin:0 auto;padding:20px 16px 48px}}h1{{margin:0;font-size:24px}}h2{{font-size:17px;margin:26px 0 8px}}p.lead{{color:var(--muted);margin:4px 0}}
.box{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:4px 10px;overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:14px}}td,th{{text-align:left;padding:6px;border-bottom:1px solid var(--line);vertical-align:top}}th{{color:var(--muted);font-weight:600}}
.n,.sub{{color:var(--muted);font-size:12px}}.sub{{display:block}}.w{{color:var(--ok);font-weight:700}}.l{{color:var(--no);font-weight:700}}.note{{color:var(--no)}}
</style></head><body><main>
<h1>Model Backtest</h1><p class="lead">Last {o['days']} days to {e(o['end'])} · {o['n']} finished men's pro league matches · each judged only on games before kick-off · {o.get('red_void',0)} red-card matches voided</p>{notes}
<h2>How the picks did</h2><div class="box"><table>{picks}</table></div>
<h2>Picks per day</h2><div class="box"><table><tr><th>Day</th><th>Picks</th></tr>{"".join(f"<tr><td>{e(d)}</td><td>{n}</td></tr>" for d, n in o["per_day"].items())}<tr><td><b>Average</b></td><td><b>{o["per_day_summary"]["avg"]}</b> · {o["per_day_summary"]["days_under_12"]} days under 12</td></tr></table></div>
<h2>Blind-bet baseline (every match)</h2><div class="box"><table>{rows(o['base'])}</table></div>
<h2>What each rule is worth (sides that passed the goals gate)</h2><div class="box"><table><tr><th>Rule</th><th>Side won</th><th>Side didn't lose</th></tr>{sides}</table></div>
<h2>Matches we cut: would they have landed?</h2><div class="box"><table><tr><th>Group</th><th>Bet</th><th>Hit rate</th></tr>{cuts}</table></div>
<h2>Goals gate threshold (home side, 2+/3 rules)</h2><div class="box"><table><tr><th>Gate</th><th>3/3 as 1</th><th>2+/3 as 1X</th></tr>{gate}</table></div>
<h2>Picks by country</h2><div class="box"><table>{ctry}</table></div>
<h2>Every pick</h2><div class="box"><table>{plist}</table></div>
</main></body></html>"""


if __name__ == "__main__":
    sys.exit(main())
