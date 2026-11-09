"""Renders the daily shortlist page (docs/index.html, served by GitHub Pages)."""
from datetime import datetime
from html import escape as e
from zoneinfo import ZoneInfo

VERDICT_LABEL = {"1": "Home win", "1X": "Home or draw", "X2": "Away or draw"}


def _local(iso, tz):
    return datetime.fromisoformat(iso).astimezone(ZoneInfo(tz)).strftime("%H:%M")


def _chip(ok, label, detail=""):
    cls = "ok" if ok else "no"
    mark = "✓" if ok else "✗"
    d = f'<span class="cd">{e(detail)}</span>' if detail else ""
    return f'<span class="chip {cls}">{mark} {e(label)}{d}</span>'


def _form(s):
    return "".join(f'<i class="f{c}">{c}</i>' for c in s) or "–"


def _pick_card(i, item, tz):
    f, ev = item["fixture"], item["eval"]
    b = ev["backed"]
    s = ev[b]
    home_cls = "backed" if b == "home" else ""
    away_cls = "backed" if b == "away" else ""
    co, hh = ev["common"], ev["h2h"]

    co_rows = "".join(
        f'<tr class="{r["edge"]}"><td>{e(r["opponent"])}</td>'
        f'<td>{r["home"]["res"]} {e(r["home"]["score"])}</td><td>{r["away"]["res"]} {e(r["away"]["score"])}</td></tr>'
        for r in co["rows"]
    ) or '<tr><td colspan="3" class="muted">No common opponents</td></tr>'
    h2h_rows = "".join(
        f'<li>{e(m["date"])} · {e(m["home"])} <b>{e(m["score"])}</b> {e(m["away"])}</li>' for m in hh["meetings"]
    ) or '<li class="muted">No league meetings this or last season</li>'

    side_word = "home" if b == "home" else "away"
    better = co["home_better"] if b == "home" else co["away_better"]
    worse = co["away_better"] if b == "home" else co["home_better"]
    wins = hh["home_wins"] if b == "home" else hh["away_wins"]

    return f"""
<article class="card">
  <div class="top">
    <span class="rank">{i}</span>
    <span class="badge v{e(ev['verdict'])}">{e(ev['verdict'])}</span>
    <span class="meta">{_local(f['date'], tz)} · {e(f['country'])} · {e(f['league'])}</span>
  </div>
  <h3><span class="{home_cls}">{e(f['home'])}</span> <span class="vs">v</span> <span class="{away_cls}">{e(f['away'])}</span></h3>
  <p class="call">{VERDICT_LABEL[ev['verdict']]} · backing the {side_word} side · {s['score']}/3 rules</p>
  <div class="chips">
    {_chip(s['gate']['pass'], 'Goals', f" {s['gate']['goals']} in last 5")}
    {_chip(s['r1'], 'Common opp.', f" +{better} / -{worse}")}
    {_chip(s['r2'], 'H2H', f" {wins} of {len(hh['meetings'])}")}
    {_chip(s['r3'], 'Form', f" {s['form']['string']}")}
  </div>
  <details>
    <summary>Show the evidence</summary>
    <div class="ev">
      <p class="lbl">Form, last 5 league games (newest first)</p>
      <p class="form"><span>{e(f['home'])}</span>{_form(ev['home']['form']['string'])}</p>
      <p class="form"><span>{e(f['away'])}</span>{_form(ev['away']['form']['string'])}</p>
      <p class="lbl">Common opponents, last 10 league games</p>
      <table><thead><tr><th>Opponent</th><th>{e(f['home'])}</th><th>{e(f['away'])}</th></tr></thead><tbody>{co_rows}</tbody></table>
      <p class="lbl">Head to head, this and last season</p>
      <ul class="h2h">{h2h_rows}</ul>
    </div>
  </details>
</article>"""


def _stat(label, s):
    if not s["settled"]:
        return f'<div class="stat"><b>–</b><span>{e(label)}</span></div>'
    return f'<div class="stat"><b>{s["pct"]}%</b><span>{e(label)} · {s["won"]}/{s["settled"]}</span></div>'


def render(day, tz, picks, cuts, stats, recent, notes, summary):
    nice_day = datetime.fromisoformat(day).strftime("%A %d %B %Y")
    cards = "".join(_pick_card(i + 1, p, tz) for i, p in enumerate(picks)) or (
        '<p class="empty">No match passed the rules today. That is the system working: no bet is better than a bad bet.</p>'
    )
    note_html = "".join(f'<p class="note">{e(n)}</p>' for n in notes)
    cut_rows = "".join(
        f'<tr><td>{_local(c["fixture"]["date"], tz)}</td><td>{e(c["fixture"]["home"])} v {e(c["fixture"]["away"])}'
        f'<span class="sub">{e(c["fixture"]["country"])} · {e(c["fixture"]["league"])}</span></td><td>{e(c["eval"]["reason"])}</td></tr>'
        for c in cuts
    )
    recent_rows = "".join(
        f'<tr><td>{e(r["date"][5:])}</td><td>{e(r["home"])} v {e(r["away"])}</td><td>{e(r["verdict"])}</td>'
        f'<td>{e(r["score"]) or "–"}</td><td class="r{e(r["result"])}">{e(r["result"])}</td></tr>'
        for r in recent
    ) or '<tr><td colspan="5" class="muted">No picks logged yet</td></tr>'

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Daily Shortlist</title>
<style>
:root{{--bg:#f6f5f1;--card:#fff;--ink:#1b1d1f;--muted:#6b7075;--line:#e3e1da;--ok:#1d7a46;--okbg:#e5f4ea;--no:#a23b2c;--nobg:#f8e6e2;--accent:#0f5c8c;--v1:#1d7a46;--v1x:#0f5c8c;--vx2:#8a5a00}}
@media (prefers-color-scheme:dark){{:root{{--bg:#121416;--card:#1b1e21;--ink:#ecebe6;--muted:#9aa0a6;--line:#2c3034;--ok:#5fcf8c;--okbg:#173225;--no:#f08a78;--nobg:#3a1f1a;--accent:#6cb6e8;--v1:#5fcf8c;--v1x:#6cb6e8;--vx2:#e5b65a}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
main{{max-width:760px;margin:0 auto;padding:20px 16px 48px}}
header h1{{margin:0;font-size:26px;letter-spacing:-.01em}}header p{{margin:4px 0 0;color:var(--muted)}}
.summary{{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0 6px}}.summary span{{background:var(--card);border:1px solid var(--line);border-radius:999px;padding:3px 10px;font-size:13px;color:var(--muted)}}
h2{{font-size:17px;margin:28px 0 10px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:12px}}
.top{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}.rank{{font-weight:700;color:var(--muted)}}
.badge{{font-weight:800;border-radius:6px;padding:1px 8px;color:#fff;font-size:14px}}.v1{{background:var(--v1)}}.v1X{{background:var(--v1x)}}.vX2{{background:var(--vx2)}}
@media (prefers-color-scheme:dark){{.badge{{color:#111}}}}
.meta{{color:var(--muted);font-size:13px}}
.card h3{{margin:8px 0 2px;font-size:18px}}.vs{{color:var(--muted);font-weight:400}}.backed{{text-decoration:underline;text-decoration-thickness:2px;text-underline-offset:3px}}
.call{{margin:0 0 8px;color:var(--muted);font-size:14px}}
.chips{{display:flex;flex-wrap:wrap;gap:6px}}.chip{{font-size:12.5px;border-radius:6px;padding:2px 8px}}.chip.ok{{background:var(--okbg);color:var(--ok)}}.chip.no{{background:var(--nobg);color:var(--no)}}.cd{{opacity:.85}}
details{{margin-top:10px}}summary{{cursor:pointer;color:var(--accent);font-size:14px}}
.lbl{{margin:12px 0 4px;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}}
.form{{margin:2px 0;display:flex;align-items:center;gap:3px}}.form span{{min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px}}
.form i{{font-style:normal;font-weight:700;font-size:12px;width:20px;text-align:center;border-radius:4px;padding:1px 0}}.fW{{background:var(--okbg);color:var(--ok)}}.fL{{background:var(--nobg);color:var(--no)}}.fD{{background:var(--line);color:var(--muted)}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}}th,td{{text-align:left;padding:5px 6px;border-bottom:1px solid var(--line);vertical-align:top}}th{{color:var(--muted);font-weight:600}}
tr.home td:nth-child(2),tr.away td:nth-child(3){{font-weight:700}}
.h2h{{margin:0;padding-left:18px;font-size:14px}}.muted{{color:var(--muted)}}
.sub{{display:block;color:var(--muted);font-size:12px}}
.stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}.stat{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px}}.stat b{{display:block;font-size:20px}}.stat span{{font-size:12px;color:var(--muted)}}
.rwon{{color:var(--ok);font-weight:700}}.rlost{{color:var(--no);font-weight:700}}.rpending,.rvoid{{color:var(--muted)}}
.note{{background:var(--nobg);color:var(--no);border-radius:8px;padding:8px 12px;font-size:14px}}
.empty{{background:var(--card);border:1px dashed var(--line);border-radius:12px;padding:18px;color:var(--muted)}}
.tablewrap{{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:4px 8px}}
footer{{margin-top:32px;color:var(--muted);font-size:12px}}
</style></head><body><main>
<header><h1>Daily Shortlist</h1><p>{e(nice_day)} · kick-off times SA time</p></header>
<div class="summary">{"".join(f"<span>{e(s)}</span>" for s in summary)}</div>
{note_html}
<h2>Picks, best first</h2>
{cards}
<h2>Track record</h2>
<div class="stats">{_stat("All picks", stats["all"])}{_stat("Home picks", stats["home"])}{_stat("Away picks", stats["away"])}{_stat("Straight 1", stats["1"])}{_stat("1X", stats["1X"])}{_stat("X2", stats["X2"])}</div>
<h2>Recent picks</h2>
<div class="tablewrap"><table><thead><tr><th>Date</th><th>Match</th><th>Bet</th><th>Score</th><th>Result</th></tr></thead><tbody>{recent_rows}</tbody></table></div>
<details><summary>Matches cut today ({len(cuts)})</summary>
<div class="tablewrap"><table><thead><tr><th>KO</th><th>Match</th><th>Why cut</th></tr></thead><tbody>{cut_rows}</tbody></table></div></details>
<footer>Rules: men's pro league games only · gate 8+ goals in last 5 · common opponents · H2H 2 of last 3 (this + last season) · form 3W and at most 1L in last 5 · home 3/3 = 1, home 2/3 = 1X, away 3/3 = X2. Data: API-Football.</footer>
</main></body></html>"""
