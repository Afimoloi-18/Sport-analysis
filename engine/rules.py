"""The rulebook. Pure functions over normalised league games.

A game is a dict: id, date (ISO string), season, league_id, home_id, away_id, home, away, hg, ag.
Only finished men's professional LEAGUE games may be passed in.

Rulebook (agreed):
  Gate   backed team scored >= 8 goals in its last 5 league games, else cut.
  Rule 1 common opponents from each team's last 10 league games. Result vs each shared
         opponent (W > D > L, margins ignored; most recent meeting if played twice).
         Pass if better against >= 1 and worse against none.
  Rule 2 H2H: last 3 league meetings within current + previous season; >= 2 wins.
         Fewer than 2 meetings in the window = fail.
  Rule 3 form: last 5 league games, >= 3 wins and <= 1 loss.
  Verdict  Home 3/3 = 1 | Home 2/3 = 1X | Away 3/3 = X2 | Away 2/3 = cut | < 2/3 = cut.
  Ranking  home 1, then home 1X, then away X2.
"""

RANK = {"W": 2, "D": 1, "L": 0}


def outcome(game, team_id):
    if game["home_id"] == team_id:
        gf, ga = game["hg"], game["ag"]
    else:
        gf, ga = game["ag"], game["hg"]
    return ("W" if gf > ga else "D" if gf == ga else "L"), gf, ga


def opponent(game, team_id):
    if game["home_id"] == team_id:
        return game["away_id"], game["away"]
    return game["home_id"], game["home"]


def last_games(games, team_id, before, n):
    mine = [g for g in games if (g["home_id"] == team_id or g["away_id"] == team_id) and g["date"] < before]
    mine.sort(key=lambda g: g["date"], reverse=True)
    return mine[:n]


def gate(games5, team_id, cfg):
    goals = sum(outcome(g, team_id)[1] for g in games5)
    ok = len(games5) >= cfg["gate_last_n"] and goals >= cfg["gate_min_goals"]
    return {"pass": ok, "goals": goals, "games": len(games5)}


def form(games5, team_id, cfg):
    res = [outcome(g, team_id)[0] for g in games5]
    w, d, l = res.count("W"), res.count("D"), res.count("L")
    ok = len(res) >= cfg["form_last_n"] and w >= cfg["form_min_wins"] and l <= cfg["form_max_losses"]
    return {"pass": ok, "string": "".join(res), "w": w, "d": d, "l": l}


def _results_by_opponent(games10, team_id):
    out = {}
    for g in sorted(games10, key=lambda g: g["date"], reverse=True):  # most recent first wins
        oid, oname = opponent(g, team_id)
        if oid not in out:
            r, gf, ga = outcome(g, team_id)
            out[oid] = {"name": oname, "res": r, "score": f"{gf}-{ga}", "date": g["date"][:10]}
    return out


def common_opponents(home10, home_id, away10, away_id):
    """Returns per-side pass flags plus the comparison table."""
    rh = _results_by_opponent(home10, home_id)
    ra = _results_by_opponent(away10, away_id)
    shared = (set(rh) & set(ra)) - {home_id, away_id}
    rows, home_better, away_better = [], 0, 0
    for oid in shared:
        h, a = rh[oid], ra[oid]
        if RANK[h["res"]] > RANK[a["res"]]:
            edge = "home"
            home_better += 1
        elif RANK[h["res"]] < RANK[a["res"]]:
            edge = "away"
            away_better += 1
        else:
            edge = "level"
        rows.append({"opponent": h["name"], "home": h, "away": a, "edge": edge})
    rows.sort(key=lambda r: r["opponent"])
    return {
        "home_pass": home_better >= 1 and away_better == 0,
        "away_pass": away_better >= 1 and home_better == 0,
        "home_better": home_better,
        "away_better": away_better,
        "rows": rows,
    }


def head_to_head(games, home_id, away_id, seasons, before, cfg):
    meets = [
        g for g in games
        if {g["home_id"], g["away_id"]} == {home_id, away_id} and g["season"] in seasons and g["date"] < before
    ]
    meets.sort(key=lambda g: g["date"], reverse=True)
    last = meets[: cfg["h2h_last_n"]]
    hw = sum(1 for g in last if outcome(g, home_id)[0] == "W")
    aw = sum(1 for g in last if outcome(g, away_id)[0] == "W")
    enough = len(last) >= cfg["h2h_min_meetings"]
    return {
        "home_pass": enough and hw >= cfg["h2h_min_wins"],
        "away_pass": enough and aw >= cfg["h2h_min_wins"],
        "meetings": [
            {"date": g["date"][:10], "home": g["home"], "away": g["away"], "score": f'{g["hg"]}-{g["ag"]}'}
            for g in last
        ],
        "home_wins": hw,
        "away_wins": aw,
    }


def evaluate(fixture, games, cfg):
    """fixture: dict with home_id, away_id, home, away, date, season. games: all known league games."""
    h, a, before = fixture["home_id"], fixture["away_id"], fixture["date"]
    seasons = {fixture["season"], fixture["season"] - 1}

    h5 = last_games(games, h, before, cfg["form_last_n"])
    a5 = last_games(games, a, before, cfg["form_last_n"])
    h10 = last_games(games, h, before, cfg["common_last_n"])
    a10 = last_games(games, a, before, cfg["common_last_n"])

    side = {}
    co = common_opponents(h10, h, a10, a)
    hh = head_to_head(games, h, a, seasons, before, cfg)
    for key, tid, g5 in (("home", h, h5), ("away", a, a5)):
        gt = gate(g5, tid, cfg)
        fm = form(g5, tid, cfg)
        r1, r2, r3 = co[f"{key}_pass"], hh[f"{key}_pass"], fm["pass"]
        side[key] = {"gate": gt, "form": fm, "r1": r1, "r2": r2, "r3": r3, "score": int(r1) + int(r2) + int(r3)}

    H, A = side["home"], side["away"]
    home_ok = H["gate"]["pass"] and H["score"] >= 2
    away_live = A["gate"]["pass"] and A["score"] >= 2

    verdict, backed, reason = None, None, ""
    if home_ok and away_live:
        reason = "Conflict: both teams pass 2+ rules"
    elif home_ok:
        backed, verdict = "home", ("1" if H["score"] == 3 else "1X")
    elif A["gate"]["pass"] and A["score"] == 3:
        backed, verdict = "away", "X2"
    else:
        reason = _cut_reason(H, A)

    return {
        "verdict": verdict,
        "backed": backed,
        "reason": reason,
        "home": H,
        "away": A,
        "common": co,
        "h2h": hh,
        "history": {"home_games": len(h10), "away_games": len(a10)},
    }


def _cut_reason(H, A):
    def why(s, label):
        if not s["gate"]["pass"]:
            if s["gate"]["games"] < 5:
                return f"{label}: under 5 league games on record"
            return f'{label}: gate fail ({s["gate"]["goals"]} goals in last 5)'
        return f'{label}: {s["score"]}/3 rules'

    if A["gate"]["pass"] and A["score"] == 2:
        return "Away 2/3 (downgraded to cut)"
    return f'{why(H, "Home")}; {why(A, "Away")}'


def rank_key(item):
    order = {"1": 0, "1X": 1, "X2": 2}
    ev = item["eval"]
    backed = ev[ev["backed"]]
    return (order[ev["verdict"]], -backed["gate"]["goals"], item["fixture"]["date"])
