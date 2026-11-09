# Sport-analysis: daily soccer shortlist

Every morning at about 07:00 SA time, GitHub runs `run.py` in the cloud. It:

1. Settles earlier picks (won/lost) in `data/results_log.csv`
2. Pulls today's fixtures from API-Football and keeps **men's professional league games only** (no women, youth/reserve, cups or friendlies)
3. Applies the rulebook (below) to every remaining match
4. Publishes the ranked shortlist at `https://afimoloi-18.github.io/Sport-analysis/` and sends it to Telegram

## Rulebook
| Step | Rule |
|---|---|
| Gate | Backed team scored **8+ goals in its last 5 league games**, else cut |
| Rule 1 | **Common opponents** (last 10 league games each): better than the other team against at least one shared opponent and worse against none (W > D > L, margins ignored) |
| Rule 2 | **H2H**: at least 2 wins in the last 3 league meetings, this + last season only. Under 2 meetings = fail |
| Rule 3 | **Form**: last 5 league games, at least 3 wins and at most 1 loss |
| Verdict | Home 3/3 = **1** · Home 2/3 = **1X** · Away 3/3 = **X2** · Away 2/3 = cut · under 2/3 = cut |
| Ranking | Home 1, then home 1X, then away X2 |

Edge cases: if a team played a common opponent twice, the most recent meeting counts. If *both* teams pass 2+ rules, the match is cut as a conflict.

## One-time setup (phone is fine)
1. **API key**: sign up free at dashboard.api-football.com. Then go to repo **Settings → Secrets and variables → Actions → New repository secret**, name it `API_FOOTBALL_KEY`, and paste the key.
2. **Telegram**: add secret `TELEGRAM_BOT_TOKEN` (from @BotFather), then send your bot any message. The first run finds your chat automatically.
3. **Page**: **Settings → Pages → Build and deployment → Deploy from a branch → `main` / `/docs` → Save**.
4. **First run**: **Actions → Daily shortlist → Run workflow**.

## Tuning
All thresholds and league filters live in `config.json`. Add a league id to `exclude_league_ids` to block a league, or list ids in `include_only_league_ids` to check only those.

The free API plan allows 100 calls a day. One league costs 2 calls (this + last season) and covers every match in it that day, so the biggest leagues are checked first.
