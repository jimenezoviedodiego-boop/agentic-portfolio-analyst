# Portfolio Tracker — Design

Date: 2026-09-16
Status: Approved for implementation planning (revision 2 — adds cost
basis/G-P tracking, fundamentals, and a summary report, per the owner's
feedback after revision 1)

## Purpose

The owner holds a fixed set of long-term stock positions (plus one ETF) and
does not want to discover new stocks to buy — the goal is purely to
understand movement in what he already owns: when a holding is up or
down, why, and what its broader health looks like (valuation, debt,
etc.), so he can spot good moments to add to an existing position. This
is a WAT (Workflows, Agents, Tools) subsystem: deterministic tools fetch
data, the agent (Claude) reads that data and writes the "why"/status
narrative, workflows document the SOP for both.

The owner's actual holdings (from his broker account) were
provided during design and are captured in `data/portfolio.yaml` (see
Data model) — gitignored, never committed.

## Non-goals

- No stock discovery / screening / recommendations for new tickers.
- No automated trading or order placement.
- No scheduled/cron automation in this iteration — every update is
  triggered manually by the owner asking for it.

## Data model

All persistent data lives under `data/`, which is gitignored (contains
personal financial holdings and amounts).

```
data/
  portfolio.yaml            # source of truth for current holdings
  prices/<TICKER>.csv       # date, open, high, low, close, volume
  news/<TICKER>.jsonl       # one headline per line
  fundamentals/<TICKER>.yaml # dated snapshots: PE, debt, dividend yield, etc.
  analysis/<TICKER>.yaml    # dated narrative + status entries
  portfolio_history.csv     # dated snapshot: value/G-P per holding, for P&L trend
```

`portfolio.yaml`:
```yaml
holdings:
  - ticker: HON
    company: Honeywell International
    isin: US4385161066
    exchange: NYSE
    currency: USD
    shares: 10
    avg_cost_local: 120.50   # broker breakeven price, in the  
                                   # instrument's trading currency
    notes: ""
```

- `shares` is share count, updated whenever the owner tells the agent about a
  buy/sell.
- `avg_cost_local` is the average cost basis per share (the broker's breakeven
  price column), used with live FX rates to compute EUR-denominated unrealized
  gain/loss. **Assumption to validate during implementation:** the breakeven price is
  assumed to be in the instrument's own trading currency (matching the
  `Mon.` column), not pre-converted to EUR. Before trusting the computed
  G/P numbers, cross-check them against the G/P€ / G/P% figures the owner
  pasted for 2-3 holdings and adjust the assumption if they don't line
  up.
- The owner updates holdings (shares, or a new/removed position) by telling
  the agent in chat; the agent edits `portfolio.yaml` directly. No
  dedicated CLI tool for this — it's simple structured text (YAGNI).

`data/prices/<TICKER>.csv` — standard OHLCV columns, one row per trading
day, deduplicated by date.

`data/news/<TICKER>.jsonl` — one JSON object per line, deduped by `url`:
```json
{"date": "2026-09-15", "title": "...", "source": "...", "url": "...", "fetched_at": "2026-09-16T10:00:00Z"}
```

`data/fundamentals/<TICKER>.yaml` — list of dated snapshots so
fundamentals can be compared over time, not just viewed as a single
latest value:
```yaml
snapshots:
  - date: "2026-09-16"
    pe_ratio: 22.4
    forward_pe: 20.1
    debt_to_equity: 145.3
    dividend_yield: 2.8
    market_cap: 68000000000
    profit_margin: 0.11
    fifty_two_week_range: [118.5, 168.2]
```

`data/analysis/<TICKER>.yaml` — dated entries combining the price-move
narrative and the fundamentals-based status:
```yaml
entries:
  - date: "2026-09-16"
    price_change_pct: 4.2
    window: "since 2026-09-09"
    price_narrative: "Up 4% this week, driven by strong iPhone sell-through reports."
    status: "Valuation reasonable at 22x P/E vs 5y avg of ~25x. Debt/equity elevated but stable. Dividend yield 2.8%, well covered."
    watch: "Upcoming earnings call on 2026-10-15 — guidance revision risk."
```

`data/portfolio_history.csv` — one row per holding per update run:
`date, ticker, shares, price_local, currency, value_eur, avg_cost_local,
gp_eur, gp_pct`. This gives a time series of the portfolio's overall
unrealized P&L, not just a snapshot, mirroring the price/news history
approach.

## Tools (`tools/`)

Each tool is a standalone, single-purpose Python script, runnable from
the CLI and callable by the agent. No API keys required for v1.

1. **`fetch_prices.py --ticker TICKER [--start YYYY-MM-DD]`**
   - Pulls daily OHLCV via `yfinance`.
   - First run: backfill last 30 days. Later runs: fetch only from the
     day after the last cached date through today.
   - Appends new rows, dedups by date.

2. **`fetch_news.py --ticker TICKER --company "Company Name"`**
   - Pulls recent headlines from Google News RSS (`feedparser`, no key
     needed). Appends new items, deduped by URL.

3. **`fetch_fundamentals.py --ticker TICKER`**
   - Pulls current fundamentals via `yfinance`'s `Ticker.info`: trailing
     P/E, forward P/E, debt-to-equity, dividend yield, market cap, profit
     margin, 52-week range (extendable — "anything relevant" per the owner,
     starting with this standard set).
   - Appends a dated snapshot to `data/fundamentals/<TICKER>.yaml`.

4. **`fetch_fx_rate.py --pair USDEUR`**
   - Small helper: pulls a spot FX rate via `yfinance` (e.g.
     `EURUSD=X`), used to convert non-EUR holdings (USD, CHF) into EUR
     for the value/G-P calculations. Cached per day, not re-fetched
     within the same run.

5. **`sync_google_sheet.py`**
   - Reads portfolio + prices + fundamentals + portfolio_history for
     every holding.
   - **Overview** tab: ticker, company, shares, latest price, value
     (EUR), avg cost, G/P € , G/P %, P/E, dividend yield, last updated.
   - One tab per ticker: date-indexed price history alongside news
     headlines.
   - Uses OAuth (`credentials.json` + `token.json`).

6. **`sync_summary_doc.py`**
   - Reads `data/analysis/<TICKER>.yaml` (latest entry per holding) plus
     current G/P.
   - Writes/updates a single Google Doc ("Portfolio Summary") with one
     section per company: current status (valuation/debt/dividend
     health), the price-move narrative, G/P, and the biggest thing to
     watch going forward.
   - Same OAuth credentials as the Sheet, with the Docs API scope added.

Dependencies to add: `yfinance`, `feedparser`, `gspread`, `google-auth`,
`google-auth-oauthlib`, `google-api-python-client` (for Docs), `pyyaml`.

## Workflows (`workflows/`)

**`update_portfolio.md`** — triggered when the owner asks to update his
portfolio:
1. Read `data/portfolio.yaml`.
2. For each holding: run `fetch_prices.py`, `fetch_news.py`,
   `fetch_fundamentals.py`; run `fetch_fx_rate.py` once per currency
   needed (USD, CHF, EUR).
3. Compute `value_eur` and `gp_eur`/`gp_pct` per holding; append a row to
   `data/portfolio_history.csv`.
4. For each holding, the agent writes:
   - a price-move narrative grounded in the fetched news (or states
     plainly that no notable news was found),
   - a status line synthesizing the fundamentals (valuation, debt,
     dividend health),
   - a "biggest thing to watch" note (e.g. upcoming earnings, a
     debt-related headline, a notably stretched valuation).
   Appended to `data/analysis/<TICKER>.yaml`.
5. Run `sync_google_sheet.py`, then `sync_summary_doc.py`.
6. Report a short summary back to the owner in chat (what moved, by how
   much, and the one-line reason where known).

**`add_holding.md`** — triggered when the owner mentions a buy/sell in chat:
1. Agent edits `data/portfolio.yaml` (add/adjust `shares`, and
   `avg_cost_local` for a new position — asks the owner for it if not
   given).
2. If it's a new ticker: run the same fetch/analyze/sync steps as
   `update_portfolio.md`, scoped to just that ticker.

## Error handling

- **Ticker lookup fails**: agent asks the owner for the correct symbol.
- **Price/news/fundamentals API down or rate-limited**: tool exits with
  a clear error; agent reports the failure rather than fabricating data
  or silently skipping the holding.
- **No news found in window**: narrative says so explicitly.
- **FX rate unavailable**: EUR conversion for that currency is skipped
  for the run, native-currency value is still reported, and the agent
  flags that EUR figures are stale/incomplete.
- **Google auth missing/expired**: sync tools error out with
  instructions to re-run the OAuth consent flow; local data is still
  saved regardless, so nothing is lost even if sync fails.

## Setup required (one-time, manual)

The owner needs a Google Cloud project with the Sheets API, Drive API, and
Docs API enabled, and an OAuth client downloaded as `credentials.json` in
the project root. The first run of a sync tool opens a browser consent
screen and saves `token.json`. The owner has asked for a walkthrough of this
during implementation.

## Testing approach

No unit-test framework needed for v1 — these are thin I/O wrapper
scripts around external APIs. Verification: run each tool manually
against a few of the owner's real holdings and confirm output looks correct,
**specifically validating the G/P calculation against the real numbers
The owner pasted** before trusting it going forward. Per the self-improvement
loop in `CLAUDE.md`, issues found get fixed in the tool and documented in
the workflow.

## Out of scope for this spec (future iterations)

- Scheduled/automatic daily updates (manual trigger only for now).
- Realized gains, dividends received, or transaction history — only
  current unrealized position P&L.
- Alerting/notifications on big moves.
