# Technical Analysis (MACD, RSI, Konkorde) — Design

Date: 2026-09-18
Status: Approved for implementation planning

## Purpose

Add technical analysis to every ticker tab of the "Portfolio Tracker"
Google Sheet: RSI, MACD and Konkorde indicator values plus native,
hoverable Sheets charts, and a compact summary of the latest signals on
the Overview tab so all holdings can be scanned at once.

## Non-goals

- Technical signals do NOT feed into the existing Rating / Overall
  Score / 4 dimension scores. Those stay exactly as they are.
- No changes to the summary Google Doc (its legend is not extended).
- No rendered images (matplotlib/PNG) — charts are native Sheets charts.
- No new persisted data file: indicators are derived from the price CSVs
  at sync time.

## 1. Data: one year of OHLCV

Current price CSVs hold only ~24 trading days (default 30-day lookback),
which is too short: MACD's signal line needs 35 bars, Konkorde needs
~105 bars (EMA15 + 90-bar highest/lowest window).

- One-time backfill: `python -m tools.fetch_prices --ticker <T> --start 2025-09-18`
  for every holding. `append_dedup_csv` dedupes on `date`, so overlap
  with existing rows is harmless.
- `fetch_prices.compute_start_date` default lookback changes 30 → 365
  days, so new holdings (via `workflows/add_holding.md`) also get a year.
- `fetch_prices` already stores `open, high, low, close, volume` — all
  that Konkorde needs.

## 2. Indicator engine: `tools/technicals.py`

Pure functions (pandas), no I/O, no Google calls. Input: price rows as
loaded by `load_csv_rows(price_csv_path(ticker))` (strings); output: a
per-date list of dicts with float values or `None` during warm-up.

- **RSI(14)** — Wilder smoothing (`ewm(alpha=1/14, adjust=False)` of
  gains/losses, seeded conventionally). Computed on close.
- **MACD(12, 26, 9)** — `EMA12(close) - EMA26(close)`; signal =
  `EMA9(MACD)`; histogram = MACD − signal. EMAs are `ewm(span=n,
  adjust=False)`. Values before bar 26 (MACD) / bar 34 (signal,
  histogram) are `None`.
- **Konkorde (Blai5)**, on `tprice = (open + high + low + close) / 4`:
  - PVI: starts at 1; on bars where `volume > volume[-1]`,
    `pvi += (tprice - tprice[-1]) / tprice[-1] * pvi[-1]`, else unchanged.
  - NVI: same, but on bars where `volume < volume[-1]`.
  - `pvim = EMA15(pvi)`; `oscp = (pvi - pvim) * 100 / (highest(pvim, 90) - lowest(pvim, 90))`.
  - `nvim = EMA15(nvi)`; **blue (azul)** `= (nvi - nvim) * 100 / (highest(nvim, 90) - lowest(nvim, 90))`.
  - `xmf = MFI(tprice, volume, 14)`.
  - Bollinger oscillator: `basis = SMA25(tprice)`, `dev = 2 * stdev25(tprice)`;
    `boll = (tprice - (basis - dev)) / (2 * dev) * 100`.
  - `xrsi = RSI14(tprice)`.
  - `stoc = 100 * (tprice - lowest(low, 21)) / (highest(high, 21) - lowest(low, 21))`.
  - **brown (marrón)** `= (xrsi + xmf + boll + stoc / 3) / 2`.
  - **green (verde)** `= brown + oscp`.
  - **average (media)** `= EMA15(brown)`.
  - Any value whose rolling windows aren't full is `None`; a zero
    denominator (flat range) yields `None`, never a crash or inf.
- **Latest-signal summary** `latest_signals(indicator_rows)` → dict:
  - `rsi`: last RSI value (float or None).
  - `macd_signal`: `"Bullish"` if MACD > signal else `"Bearish"`; suffix
    `" ↑ cross"` / `" ↓ cross"` if the MACD/signal relationship flipped
    within the last 3 bars. `""` if not enough data.
  - `konkorde_signal`: `"Sharks buying"` if blue > 0 else
    `"Sharks selling"`; `""` if not enough data.

## 3. Ticker tabs

Column layout (replacing the current `Date | Close | News`):

| Visible | Hidden (helper, for charts) |
|---|---|
| Date, Close, RSI, MACD, Signal, Histogram, Konkorde Green, Konkorde Brown, Konkorde Blue, Konkorde Avg, News | RSI 70, RSI 30, Hist +, Hist − |

- `News` stays last among visible columns; helper columns come after it
  and are hidden via `updateDimensionProperties(hiddenByUser=true)`.
- `Hist +` = histogram where ≥ 0 else blank; `Hist −` = histogram where
  < 0 else blank — so the MACD histogram renders green/red with two
  column series.
- Numbers are written as real numbers rounded to 4 decimals; `None` →
  empty cell.
- Header row frozen.

Charts (native Sheets `addChart`, `basicChart`), stacked vertically to
the right of the data (anchored at the first column after the helpers),
each covering **one contiguous range spanning the full year of history**
in the tab. (An earlier version windowed to the last ~126 rows/~6 months
via multiple sourceRanges, but the Sheets API rejects more than one
sourceRange per domain/series, so it shipped as a single contiguous range
covering everything instead.)

1. **Price** — LINE: Close.
2. **MACD** — COMBO: Hist + (green COLUMN), Hist − (red COLUMN), MACD
   (blue LINE), Signal (orange LINE).
3. **RSI** — LINE: RSI, plus RSI 70 / RSI 30 as dashed grey lines.
4. **Konkorde** — COMBO: Green (green AREA), Brown (brown AREA), Blue
   (blue AREA), Avg (red LINE).

Re-sync behaviour: all existing charts on the ticker tab are deleted and
re-created in the same single `batch_update` as the hide-columns request
(one write per tab), mirroring how `clear_conditional_formats` prevents
rule pile-up. Chart IDs come from one `fetch_sheet_metadata()` call per
sync, not per tab.

## 4. Overview and Legend

Three new Overview columns, appended after the existing score columns
and before `P/E`: **RSI**, **MACD**, **Konkorde** (values from
`latest_signals`).

- RSI conditional formatting: > 70 red text (overbought), < 30 green
  text (oversold), using the existing `DELTA_DOWN_COLOR` /
  `DELTA_UP_COLOR`.
- MACD / Konkorde text: "Bullish…"/"Sharks buying" green, "Bearish…"/
  "Sharks selling" red (TEXT_STARTS_WITH rules).
- Rating / Overall Score / dimension scores are unchanged.

Legend tab: three new rows (RSI, MACD, Konkorde) explaining what each
indicator measures and how to read the colors/signals. These are
Sheet-only entries (a `TECHNICAL_LEGEND_SECTIONS` list appended in
`build_legend_rows`), so the Doc's legend is unaffected.

## 5. Error handling and quota

- Sheets write quota (~60 writes/min/user): switch
  `gspread.authorize(...)` to use `http_client=gspread.BackOffHTTPClient`
  so 429s are retried with backoff instead of failing the sync.
- A ticker with too little history still gets a tab; indicator cells
  are blank and charts are still created (they render what exists).
  Overview signal cells are blank.
- Tickers with zero volume data (e.g. some ETF days) → PVI/NVI simply
  don't move on those bars; no special-casing needed beyond the
  zero-denominator → `None` rule.

## 6. Testing

- `tests/test_technicals.py`:
  - RSI against a hand-computed/reference series (e.g. the classic
    Wilder 14-period example) and edge cases (all gains → 100, flat → no crash).
  - MACD against values computed independently with plain pandas ewm in
    the test; warm-up `None`s at the right indices.
  - Konkorde: warm-up length, `None` on flat ranges, green − brown ==
    oscp relationship, output length == input length.
  - `latest_signals`: bullish/bearish, cross detection, empty input.
- `tests/test_sync_google_sheet.py`: new ticker-tab row layout, Overview
  header/row includes the 3 new columns, chart request builder produces
  4 `addChart` requests + deletes for existing chart IDs + hide request
  (pure function, no network).
- Live verification: backfill, run `python -m tools.sync_google_sheet`,
  open the Sheet and visually confirm the 4 charts on a couple of tabs
  and the Overview columns.

## 7. Workflow updates

- `workflows/update_portfolio.md`: deliverable section mentions the
  technical indicators/charts; Notes gets the one-time 1-year backfill
  and the 365-day default.
- `workflows/add_holding.md`: note that the first `fetch_prices` pulls
  a year, which the technical charts need.
