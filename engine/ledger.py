"""Results log: every pick is recorded, then settled on a later run."""
import csv
import os

from .api import ApiError, BudgetExceeded
from .data import norm

LOG = os.path.join("data", "results_log.csv")
FIELDS = ["date", "fixture_id", "kickoff", "country", "league", "home", "away",
          "backed", "verdict", "rules", "score", "result"]
VOID = {"PST", "CANC", "ABD", "AWD", "WO"}


def read():
    if not os.path.exists(LOG):
        return []
    with open(LOG, newline="") as fh:
        return list(csv.DictReader(fh))


def write(rows):
    os.makedirs("data", exist_ok=True)
    with open(LOG, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def add_picks(rows, picks, day):
    have = {r["fixture_id"] for r in rows}
    for p in picks:
        f, ev = p["fixture"], p["eval"]
        if str(f["id"]) in have:
            continue
        rows.append({
            "date": day, "fixture_id": f["id"], "kickoff": f["date"], "country": f["country"],
            "league": f["league"], "home": f["home"], "away": f["away"], "backed": ev["backed"],
            "verdict": ev["verdict"], "rules": ev[ev["backed"]]["score"], "score": "", "result": "pending",
        })
    return rows


def won(verdict, hg, ag):
    if verdict == "1":
        return hg > ag
    if verdict == "1X":
        return hg >= ag
    if verdict == "X2":
        return ag >= hg
    return False


def settle(api, rows, log):
    pending = [r for r in rows if r["result"] == "pending"]
    by_id = {str(r["fixture_id"]): r for r in pending}
    ids = list(by_id)
    for i in range(0, len(ids), 20):
        try:
            resp = api.get("/fixtures", ids="-".join(ids[i:i + 20]))
        except (ApiError, BudgetExceeded) as e:
            log(f"Settling stopped: {e}")
            break
        for g in map(norm, resp):
            r = by_id.get(str(g["id"]))
            if not r:
                continue
            if g["status"] in ("FT", "AET", "PEN") and g["hg"] is not None:
                r["score"] = f'{g["hg"]}-{g["ag"]}'
                r["result"] = "won" if won(r["verdict"], g["hg"], g["ag"]) else "lost"
            elif g["status"] in VOID:
                r["result"] = "void"
    return rows


def stats(rows):
    def rate(sub):
        s = [r for r in sub if r["result"] in ("won", "lost")]
        w = sum(1 for r in s if r["result"] == "won")
        return {"won": w, "settled": len(s), "pct": round(100 * w / len(s)) if s else None}

    return {
        "all": rate(rows),
        "home": rate([r for r in rows if r["backed"] == "home"]),
        "away": rate([r for r in rows if r["backed"] == "away"]),
        "1": rate([r for r in rows if r["verdict"] == "1"]),
        "1X": rate([r for r in rows if r["verdict"] == "1X"]),
        "X2": rate([r for r in rows if r["verdict"] == "X2"]),
        "pending": sum(1 for r in rows if r["result"] == "pending"),
    }
