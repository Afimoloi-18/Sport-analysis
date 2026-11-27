"""Pre-match odds for a pick (1 call per pick). Prefers Betway, else the first bookmaker quoting the bet."""
from .api import ApiError

WANT = {"1": ("Match Winner", "Home"), "1X": ("Double Chance", "Home/Draw"), "X2": ("Double Chance", "Draw/Away")}


def pick_odds(api, fixture_id, verdict, prefer="betway"):
    bet_name, value = WANT[verdict]
    try:
        resp = api.get("/odds", fixture=fixture_id)
    except ApiError:
        return None, None
    found = []
    for item in resp:
        for bk in item.get("bookmakers", []):
            for bet in bk.get("bets", []):
                if bet.get("name") == bet_name:
                    for v in bet.get("values", []):
                        if v.get("value") == value:
                            try:
                                found.append((bk.get("name", ""), float(v["odd"])))
                            except (TypeError, ValueError):
                                pass
    if not found:
        return None, None
    for name, odd in found:
        if prefer in name.lower():
            return odd, name
    return found[0][1], found[0][0]
