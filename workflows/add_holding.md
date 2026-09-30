# Workflow: Add / Update a Holding

**Trigger:** the owner mentions a buy, sell, or share-count change in chat
(e.g. "I bought 5 more shares of AAPL", "I sold my Bristol-Myers position").

**Objective:** Keep `data/portfolio.yaml` accurate, and make sure a new
position gets its initial data pulled immediately rather than waiting
for the next full `update_portfolio` run.

**Steps:**

1. Determine what changed:
   - **New position:** need ticker, company name, ISIN (optional),
     exchange, currency, shares, and cost basis (`avg_cost_local`) — ask
     the owner for whatever isn't given. Before saving a new ticker to
     `data/portfolio.yaml`, verify the symbol actually resolves to the
     intended company — e.g. check `yf.Ticker(<TICKER>).info`'s
     `longName`/`currency`/`exchange` against what the owner described — and
     do not save it until they match. This is the same check that would
     have caught the `SAN` incident (plain `SAN` silently resolved to
     Banco Santander instead of Sanofi). If the ticker needs a
     Yahoo Finance exchange suffix (e.g. `.PA`, `.SW`, `.AS`) to resolve
     correctly, record why in that holding's `notes` field, the same way
     `SAN.PA`, `NOVN.SW`, and `VWRL.AS` already document their suffix
     rationale.
   - **Existing position, shares changed:** update `shares` for that
     ticker.
   - **Position closed:** remove the holding entry entirely (or move it
     to a `notes` field noting it was closed, if the owner wants history
     kept — ask which he prefers). Also delete that ticker's worksheet
     tab from the live Google Sheet — `sync_google_sheet.py` only
     creates/updates tabs for tickers still in `data/portfolio.yaml`, it
     does not prune stale ones automatically, so a closed position's tab
     is left behind unless removed by hand (this already required manual
     cleanup once during the `SAN` → `SAN.PA` rename).

2. Edit `data/portfolio.yaml` directly (it's simple structured YAML —
   no dedicated tool needed for this step, per the design spec's YAGNI
   call).

3. If it's a **new ticker**, run the full per-holding sequence from
   `update_portfolio.md` steps 2, 4-6 scoped to just that ticker:
   ```
   python -m tools.fetch_prices --ticker <TICKER>
   # ^ pulls a year of daily prices by default; the ticker tab's
   #   technical charts need ~105 trading days before Konkorde
   #   shows any values.
   python -m tools.fetch_news --ticker <TICKER> --company "<COMPANY>"
   python -m tools.fetch_fundamentals --ticker <TICKER>
   python -m tools.record_snapshot
   python -m tools.append_analysis --ticker <TICKER> ...
   python -m tools.sync_google_sheet
   python -m tools.sync_summary_doc
   ```

   If it's an **existing ticker** (shares changed, or a position
   closed), the price/news/fundamentals data for that ticker is already
   current from the last `update_portfolio` run — no need to re-fetch.
   Just re-run the two steps that recompute value/gain-loss from the
   updated `data/portfolio.yaml` and push it to Google:
   ```
   python -m tools.record_snapshot
   python -m tools.sync_google_sheet
   ```
   (`sync_summary_doc` is optional here since the Doc's narrative
   sections aren't affected by a share-count change alone — run it too
   if the owner wants the Doc's holdings table current immediately rather
   than at the next full update.)

4. Confirm the change with the owner in chat (new share count, or the new
   position now showing up in the Sheet/Doc).

**Error handling:** same as `update_portfolio.md` — report fetch
failures rather than guessing; local `portfolio.yaml` edit always
succeeds independent of any API being reachable.

**Notes for future refinement:** update this section as real runs
surface edge cases (per the self-improvement loop in `CLAUDE.md`).

- **2026-09-16 dry run (AMZN, shares +1, then reverted):** simulated an
  existing-ticker share-count change end to end. Edited
  `data/portfolio.yaml` to bump AMZN `shares` by one, then ran
  `record_snapshot` + `sync_google_sheet` (no re-fetch needed, per the
  existing-ticker branch of step 3 above). The Overview tab's AMZN row
  updated to the new share count with recomputed value and G/P — no
  Sheet formulas needed to change, since `sync_google_sheet` writes
  computed values directly rather than spreadsheet formulas (the one
  exception: each score column's bar cell holds a `SPARKLINE` formula
  referencing the score cell in the same row, so score bars stay correct
  automatically whenever the score value itself is rewritten). Reverted
  `shares` back to the original count and re-ran
  `record_snapshot` + `sync_google_sheet`; the Overview tab confirmed
  back to the original share count and value/G-P. Confirms the
  existing-ticker path (skip fetch, just recompute + sync) works as
  documented, and that `record_snapshot`'s same-day dedup is keyed on
  `(date, ticker)` alone — it still recomputes and overwrites when the
  underlying `portfolio.yaml` shares figure changes intraday, it just
  doesn't append a second dated row for the same ticker/day.
