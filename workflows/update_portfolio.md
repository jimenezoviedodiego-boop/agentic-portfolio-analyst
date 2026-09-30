# Workflow: Update Portfolio

**Trigger:** the owner asks to update his portfolio (e.g. "update my
portfolio", "what's new with my stocks").

**Objective:** Refresh price/news/fundamentals data for every holding,
compute current value and gain/loss, write a short narrative and status
per holding, and sync everything to Google Sheets and the summary Doc.

**Deliverable format:** the Sheet's Overview tab shows Day/Week/Month %
change (colored green/red) plus 4 scores per holding — Valuation,
Momentum, and Financial Health are computed deterministically by
`record_snapshot` from fetched data (see `tools/scoring.py`); News
Sentiment is the agent's own judgment of the week's headlines, supplied
via `append_analysis` (step 5 below). Each score gets a color-coded cell
(good/warning/serious/critical) plus an in-cell bar chart. The Doc mirrors
this per company: a bordered heading, an "Overall" status label, and the
4 scores as monospace bars with a "(last: X)" comparison to the previous
run.

Every **ticker tab** carries a technical analysis of that holding: RSI(14),
MACD(12,26,9) and Konkorde columns next to the daily close, plus four
native Sheets charts stacked to the right of the data (Price, MACD, RSI,
Konkorde). The values are computed by `tools/technicals.py` at sync time
from `data/prices/<TICKER>.csv` — nothing is stored, and no agent input is
needed. The Overview tab carries the latest signal per holding in three
columns: **RSI** (red above 70 = overbought, green below 30 = oversold),
**MACD** (Bullish/Bearish, plus "↑ cross"/"↓ cross" when the lines crossed
in the last 3 trading days) and **Konkorde** ("Sharks buying"/"Sharks
selling"). These are informational only — they do NOT feed the Rating or
the 4 scores. The Legend tab explains all three.

The Doc also carries an **Analyst View** page (verdict, business view,
confidence, the four sub-scores, the case for and against, and what would
change the agent's mind per holding) followed by **Where Your Next Euro
Goes**, the holdings ranked by where a new contribution looks best placed.
The Sheet mirrors this: `Verdict`/`Confidence` columns on Overview and a
dedicated **Analyst** tab with the ranked table. See
`workflows/analyze_portfolio.md`.

The Doc opens with a **Portfolio Allocation** page (and the Sheet has a
matching **Allocation** tab): value split by sector, country and position,
"put in" vs current value per holding, and concentration flags (>10% in
one stock, >25% in one sector). It is computed by `tools/allocation.py`
from the history row plus the sector/country fields `fetch_fundamentals`
stores. No agent input is needed; it refreshes on every sync.

**Steps:**

1. Read `data/portfolio.yaml` (via `tools.portfolio_lib.load_portfolio`)
   to get the current holding list.

2. For each holding, run in order:
   ```
   python -m tools.fetch_prices --ticker <TICKER>
   python -m tools.fetch_news --ticker <TICKER> --company "<COMPANY>"
   python -m tools.fetch_fundamentals --ticker <TICKER>
   ```
   Use the ticker exactly as written in `data/portfolio.yaml` (some
   holdings need a Yahoo Finance exchange suffix — e.g. `SAN.PA`,
   `NOVN.SW`, `VWRL.AS` — see the `notes` field on each holding for why).

3. For each currency present among the holdings (USD, CHF, EUR), the FX
   rate is fetched automatically by `record_snapshot` in the next step
   — no separate step needed.

4. Run:
   ```
   python -m tools.record_snapshot
   ```
   This computes value/G-P per holding (for every holding in
   `data/portfolio.yaml`, not just the ones just fetched) and appends
   to `data/portfolio_history.csv`. Note the printed value/G-P for each
   holding — you'll use it in the next step. Appends are deduped on
   `(date, ticker)`, so re-running this on the same day after prices are
   already recorded is a safe no-op (it reuses the day's already-fetched
   closing price, prints the same figures, and does not add a new row).

5. For each holding, the agent reviews:
   - the price change (see "Computing price change" below),
   - the headlines fetched in step 2 (`data/news/<TICKER>.jsonl`),
   - the fundamentals snapshot (`data/fundamentals/<TICKER>.yaml`),

   and writes a short narrative, a status line, and a "biggest thing to
   watch" note. Ground every claim in the fetched data — if no relevant
   news turned up, say so explicitly rather than inventing a cause.

   Also assign a **news sentiment score (0-100)**: this is your own
   judgment of how the fetched headlines skew for this holding this
   week — 50 means neutral/no clear skew or too little news to judge,
   higher means the coverage is net positive, lower means net negative.
   Unlike the other 3 scores (Valuation/Momentum/Financial Health,
   computed automatically by `record_snapshot`), this one only exists
   because you assign it — base it on the same headlines you read for
   the narrative, not a separate pass.

   **Then run the analyst pass** (`workflows/analyze_portfolio.md`): it
   computes the four strategy sub-scores, and you commit to a verdict
   (Add / Hold / Stop adding — never "sell"), a business view, a
   confidence level, the case for and against, and a checkable "what
   would change my mind". Those are recorded by the same
   `append_analysis` call via its judgment flags, and `--computed-verdict`
   is required alongside `--verdict` so every disagreement with the score
   is explicit.

   Append via:
   ```
   python -m tools.append_analysis --ticker <TICKER> \
     --price-change-pct <PCT> --window "<WINDOW>" \
     --price-narrative "<NARRATIVE>" --status "<STATUS>" --watch "<WATCH>" \
     --news-sentiment-score <0-100>
   ```

   **Computing price change:** `data/portfolio_history.csv` only has one
   row per `(date, ticker)`, so "since the last recorded snapshot" only
   has a comparison point once the tracker has been run on at least two
   different days. Until then (including the very first run for a given
   holding), compute the change directly from the tail of
   `data/prices/<TICKER>.csv` instead — typically the latest close vs.
   the previous trading day's close — and say so in the window text
   (e.g. `"2026-09-15 to 2026-09-16 (1 trading day, close-to-close;
   only one dated snapshot exists in portfolio_history.csv so far)"`).
   Once multiple dated rows exist in `portfolio_history.csv` for a
   ticker, prefer diffing consecutive `value_eur` or `price_local`
   entries there instead, since that reflects the tracker's own
   snapshot cadence rather than every raw trading day.

6. Run:
   ```
   python -m tools.sync_google_sheet
   python -m tools.sync_summary_doc
   ```
   Both sync the *entire* portfolio (all holdings in
   `data/portfolio.yaml`), not just the ones touched this run — so it's
   safe (and normal) to run them even if only a subset of holdings got
   fresh analysis entries this time.

7. Report a short summary back to the owner in chat: which holdings moved
   the most (up and down), the one-line reason where known, and
   anything flagged under "watch".

**Error handling:**
- If a fetch tool errors (rate limit, network, ticker not found): report
  the specific failure to the owner, do not fabricate data for that holding,
  and continue with the remaining holdings.
- If `sync_google_sheet` or `sync_summary_doc` fails (e.g. expired
  auth): local data is already saved from steps 2-5, so nothing is
  lost. Tell the owner to re-run `python -m tools.google_auth` to refresh
  the token, then re-run the sync step alone.

**Notes for future refinement:** update this section as real runs
surface rate limits, feed quirks, or auth edge cases (per the
self-improvement loop in `CLAUDE.md`).

- **2026-09-16 dry run (AMZN, NOVN.SW):** first end-to-end run of this
  workflow. `data/portfolio_history.csv` and the per-ticker
  prices/news/fundamentals files already had today's data from earlier
  manual tool verification, so `fetch_prices`/`record_snapshot` for
  both tickers correctly no-op'd on rerun ("already up to date" / same
  printed value with no new row) — this is expected dedup behavior, not
  a bug. `fetch_news` and `fetch_fundamentals` don't dedupe by date (news
  dedupes by URL, fundamentals appends a new dated snapshot every call),
  so those re-ran and appended fresh data as normal.
  `google_news_rss_url` for `NOVN.SW` and `AMZN` both returned dozens of
  genuinely relevant, dated headlines — no thin-news issue for either
  ticker on this run.
- `sync_google_sheet`'s ticker-tab names are just the raw ticker string
  (e.g. `NOVN.SW`), which Google Sheets accepts as a worksheet title
  without issue.
- The Overview tab can display decimal numbers with a comma instead of
  a period (e.g. `45,903769`) depending on the spreadsheet's locale
  setting. This is a Sheets display/locale quirk, not a data bug — the
  underlying values written by `sync_google_sheet` and the source CSV/
  YAML files are unaffected. If this is confusing at a glance, set the
  spreadsheet locale under File > Settings in Sheets; no tool change
  needed.
- Verified end-to-end on 2026-09-16 for `AMZN` and `NOVN.SW`: both
  tickers' Overview rows, ticker tabs (price + concatenated headlines),
  and Google Doc sections showed real, current data after a full
  fetch → record_snapshot → append_analysis → sync cycle.

- **2026-09-18/21, technical analysis added.** All price CSVs were
  backfilled to one year with `python -m tools.fetch_prices --ticker <T>
  --start 2025-09-18`, and `compute_start_date`'s default lookback is now
  365 days (was 30), so a new holding fetches a year on its first run.
  The indicators need that history: RSI needs 15 trading days, MACD's
  signal line 35, and **Konkorde ~105** (EMA15 of the volume indices, then
  a 90-bar high/low window) — with one year (~252 rows) Konkorde has
  values from roughly row 104 onward, so its chart is blank on the left
  and that is expected, not a bug.
- **Sheets chart API quirks found on the first live run** (both cost a
  failed sync before they were fixed, so don't reintroduce them):
  `stackedType` must be `NOT_STACKED` — `"NONE"` is not a member of
  `BasicChartStackedType` and the whole batch is rejected; and a chart's
  domain/series may contain only **one** `sourceRange` ("each sourceRange
  across the domain & series must be in order and contiguous"), so the
  header row cannot be passed as a separate range to get series names.
  The charts therefore cover the full year of rows, with `headerCount: 1`
  inside that single range.
- `sync_google_sheet` now authorizes gspread with `BackOffHTTPClient`, so
  the ~60-writes-per-minute quota is retried with backoff instead of
  failing the sync (15 ticker tabs x clear/resize/update/charts sits close
  to that limit). Two consecutive full syncs on 2026-09-21 completed with
  no quota error and left exactly 4 charts per tab (the sync deletes the
  previous run's charts before adding new ones).
- Printing a MACD signal containing "↑"/"↓" to a Windows console raises
  `UnicodeEncodeError` (cp1252). The tools don't print signals, but if you
  add such a print, run with `PYTHONIOENCODING=utf-8`.

- **2026-09-24, NaN close from Yahoo.** For SAN.PA, NOVN.SW and VWRL.AS,
  Yahoo returned the latest session (09-23) as a volume-only row with NaN
  OHLC; `fetch_prices` stored it and `record_snapshot` valued all three at
  `nan`. `fetch_price_history` now skips rows without a close, so the next
  fetch resumes from that date once Yahoo settles it. If a snapshot ever
  prints `value nan`, check the tail of `data/prices/<T>.csv`, delete the
  NaN row and that day's history row, then re-run `fetch_prices` and
  `record_snapshot`. Separately, Yahoo simply has no 09-22 bar for some US
  tickers (HON, MCD, DE); that is an upstream gap, harmless to the
  indicators, not a tool bug.
- **Google token expiry.** `invalid_grant: Token has been expired or
  revoked` on both syncs means `token.json` is dead. If the OAuth app is in
  "Testing" mode, Google expires refresh tokens after 7 days, so expect
  this weekly unless the app is published. `google_auth` used to crash on
  a revoked token instead of re-logging in; it now falls back to the
  browser login, so `python -m tools.google_auth` is the fix.
