# Technical Analysis (MACD, RSI, Konkorde) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add RSI, MACD and Konkorde indicator columns plus 4 native Google Sheets charts to every ticker tab of the "Portfolio Tracker" Sheet, and 3 latest-signal columns to the Overview tab.

**Architecture:** A pure pandas indicator engine (`tools/technicals.py`) turns the price CSV rows into per-date indicator values. A new `tools/ticker_tab.py` builds the ticker-tab row layout and the Sheets API chart requests (pure functions, no network). `tools/sync_google_sheet.py` wires both into the existing sync: computes indicators once per ticker, writes tabs + charts (one `batch_update` per tab), adds Overview columns/formatting and Legend rows.

**Tech Stack:** Python 3, pandas 2.2, gspread 6.2.1 (Sheets API v4 `batch_update` requests), pytest.

**Spec:** `docs/superpowers/specs/2026-09-18-technical-analysis-design.md`

## Global Constraints

- Run everything from the repo root. Tools are run as modules: `python -m tools.<name>`. Tests: `python -m pytest`.
- NEVER read, write, or regenerate `data/portfolio.yaml`. Tests must never touch the real `data/` directory (the autouse fixture in `conftest.py` sandboxes `PORTFOLIO_DATA_DIR`; don't defeat it).
- Indicator parameters (exact): RSI 14 (Wilder); MACD 12/26/9; Konkorde EMA 15, range window 90, MFI 14, Bollinger 25 × 2σ (population stdev), Stochastic 21, tprice = (open+high+low+close)/4.
- Warm-up / invalid values are `None` in Python and an empty cell `""` in the Sheet — never NaN, inf, or 0.
- Numbers go to the Sheet as real Python numbers (floats/ints), never numeric strings — `ws.update` writes RAW, so strings would become text and charts would not plot them.
- Chart colors (validated colorblind-safe with the dataviz validator): up/green `#2ea36b`, down/red `#d64545`, primary/blue `#2f6fd6`, secondary/orange `#c96a12`, Konkorde brown `#a0522d`, band grey `#9e9e9e`.
- Sheets locale is es_ES: do not introduce new `CUSTOM_FORMULA` conditional-format rules (use `NUMBER_GREATER`/`NUMBER_LESS`/`TEXT_STARTS_WITH`, which have no locale issues).
- Technical signals must NOT change Rating / Overall Score / the 4 dimension scores, and must NOT change the Google Doc (`tools/sync_summary_doc.py`, `tools/scoring.LEGEND_SECTIONS`).
- Commit messages end with a blank line then `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

### Task 1: Indicator engine (`tools/technicals.py`)

**Files:**
- Create: `tools/technicals.py`
- Test: `tests/test_technicals.py`

**Interfaces:**
- Consumes: nothing from other tasks. Input rows have the shape produced by `tools.portfolio_lib.load_csv_rows(price_csv_path(ticker))`: `{"date": "YYYY-MM-DD", "open": "123.4500", "high": ..., "low": ..., "close": ..., "volume": "123456"}` (all strings).
- Produces:
  - `INDICATOR_KEYS: list[str]` = `["rsi", "macd", "macd_signal", "macd_hist", "konkorde_green", "konkorde_brown", "konkorde_blue", "konkorde_avg"]`
  - `compute_indicators(price_rows: list[dict]) -> list[dict]` — one dict per input row, sorted by date: `{"date": str, <each INDICATOR_KEYS key>: float | None}`.
  - `latest_signals(indicator_rows: list[dict]) -> dict` — `{"rsi": float | None, "macd_signal": str, "konkorde_signal": str}`.
  - `TECHNICAL_LEGEND_SECTIONS: list[tuple[str, str]]` — `(term, explanation)` pairs for RSI, MACD, Konkorde.
  - Lower-level (tested directly): `rsi(series, period=14) -> pd.Series`, `macd(close) -> (line, signal, hist)`, `konkorde(df) -> (green, brown, blue, avg)`, `_volume_index(tprice, volume, rising) -> pd.Series`, `_range_oscillator(index_series) -> pd.Series`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_technicals.py`:

```python
import math

import pandas as pd
import pytest

from tools.technicals import (
    INDICATOR_KEYS,
    TECHNICAL_LEGEND_SECTIONS,
    _range_oscillator,
    _volume_index,
    compute_indicators,
    konkorde,
    latest_signals,
    macd,
    rsi,
)

# Wilder's classic RSI worked example (as reproduced by StockCharts).
WILDER_CLOSES = [
    44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84,
    46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41,
]


def _synthetic_price_rows(n: int = 150) -> list[dict]:
    """Wavy uptrend with varying volume, in the same all-strings shape
    load_csv_rows returns for data/prices/<TICKER>.csv."""
    dates = pd.date_range("2025-01-01", periods=n, freq="B").strftime("%Y-%m-%d")
    rows = []
    for i in range(n):
        base = 100 + 10 * math.sin(i / 7) + i * 0.2
        rows.append({
            "date": dates[i],
            "open": f"{base - 0.5:.4f}",
            "high": f"{base + 1:.4f}",
            "low": f"{base - 1:.4f}",
            "close": f"{base + 0.3:.4f}",
            "volume": str(1000 + (i * 37 % 500)),
        })
    return rows


def _flat_price_rows(n: int = 150) -> list[dict]:
    dates = pd.date_range("2025-01-01", periods=n, freq="B").strftime("%Y-%m-%d")
    return [
        {"date": d, "open": "10.0", "high": "10.0", "low": "10.0", "close": "10.0", "volume": "500"}
        for d in dates
    ]


def _frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col])
    return df


def test_rsi_matches_wilder_reference_example():
    out = rsi(pd.Series(WILDER_CLOSES))

    assert out.iloc[:14].isna().all()
    # Exact (unrounded) Wilder averages. StockCharts prints 70.53 for the
    # first value only because it rounds the intermediate averages.
    assert out.iloc[14] == pytest.approx(70.46, abs=0.01)
    assert out.iloc[15] == pytest.approx(66.25, abs=0.01)
    assert out.iloc[17] == pytest.approx(69.35, abs=0.01)


def test_rsi_all_gains_is_100_and_flat_is_50():
    assert rsi(pd.Series(range(1, 31), dtype=float)).iloc[-1] == 100.0
    assert rsi(pd.Series([10.0] * 30)).iloc[-1] == 50.0


def test_macd_matches_plain_pandas_ewm_and_warms_up():
    close = pd.Series([100 + math.sin(i / 5) * 10 + i * 0.3 for i in range(80)])

    line, signal, hist = macd(close)

    expected_line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    assert line.iloc[:25].isna().all()
    assert line.iloc[25:].tolist() == pytest.approx(expected_line.iloc[25:].tolist())
    assert signal.iloc[:33].isna().all()
    assert not math.isnan(signal.iloc[33])
    assert hist.iloc[33:].tolist() == pytest.approx((line.iloc[33:] - signal.iloc[33:]).tolist())


def test_konkorde_warm_up_lengths():
    rows = compute_indicators(_synthetic_price_rows())

    # blue/green need EMA15 then a 90-bar highest/lowest window: first valid at index 14 + 89 = 103
    assert rows[102]["konkorde_blue"] is None and rows[103]["konkorde_blue"] is not None
    assert rows[102]["konkorde_green"] is None and rows[103]["konkorde_green"] is not None
    # brown's longest input is the 25-bar Bollinger window: first valid at index 24
    assert rows[23]["konkorde_brown"] is None and rows[24]["konkorde_brown"] is not None
    # avg = EMA15(brown): first valid at index 24 + 14 = 38
    assert rows[37]["konkorde_avg"] is None and rows[38]["konkorde_avg"] is not None


def test_konkorde_green_is_brown_plus_positive_volume_oscillator():
    df = _frame(_synthetic_price_rows())
    tprice = (df["open"] + df["high"] + df["low"] + df["close"]) / 4

    green, brown, _blue, _avg = konkorde(df)

    oscp = _range_oscillator(_volume_index(tprice, df["volume"], rising=True))
    valid = green.notna()
    assert valid.sum() > 0
    assert green[valid].tolist() == pytest.approx((brown[valid] + oscp[valid]).tolist())


def test_flat_prices_give_none_not_crash_or_inf():
    rows = compute_indicators(_flat_price_rows())

    for key in ("konkorde_green", "konkorde_brown", "konkorde_blue", "konkorde_avg"):
        assert all(r[key] is None for r in rows), key
    assert rows[-1]["rsi"] == 50.0
    for r in rows:
        for key in INDICATOR_KEYS:
            assert r[key] is None or math.isfinite(r[key])


def test_compute_indicators_one_row_per_input_sorted_by_date():
    price_rows = _synthetic_price_rows(40)
    shuffled = list(reversed(price_rows))

    rows = compute_indicators(shuffled)

    assert len(rows) == 40
    assert [r["date"] for r in rows] == [p["date"] for p in price_rows]
    assert set(rows[0]) == {"date", *INDICATOR_KEYS}


def test_compute_indicators_empty_input():
    assert compute_indicators([]) == []


def _row(macd_value=None, signal=None, blue=None, rsi_value=None):
    row = {"date": "2026-09-18", **{k: None for k in INDICATOR_KEYS}}
    row.update({"macd": macd_value, "macd_signal": signal, "konkorde_blue": blue, "rsi": rsi_value})
    return row


def test_latest_signals_empty_input():
    assert latest_signals([]) == {"rsi": None, "macd_signal": "", "konkorde_signal": ""}


def test_latest_signals_bullish_without_recent_cross():
    assert latest_signals([_row(2, 1)] * 5)["macd_signal"] == "Bullish"


def test_latest_signals_detects_cross_up_within_three_bars():
    rows = [_row(0, 1), _row(0, 1), _row(0, 1), _row(2, 1)]
    assert latest_signals(rows)["macd_signal"] == "Bullish ↑ cross"


def test_latest_signals_detects_cross_down_within_three_bars():
    rows = [_row(2, 1), _row(2, 1), _row(0, 1)]
    assert latest_signals(rows)["macd_signal"] == "Bearish ↓ cross"


def test_latest_signals_ignores_cross_older_than_three_bars():
    rows = [_row(2, 1), _row(0, 1), _row(0, 1), _row(0, 1), _row(0, 1)]
    assert latest_signals(rows)["macd_signal"] == "Bearish"


def test_latest_signals_konkorde_and_rsi():
    assert latest_signals([_row(blue=5.0, rsi_value=72.1)]) == {
        "rsi": 72.1, "macd_signal": "", "konkorde_signal": "Sharks buying",
    }
    assert latest_signals([_row(blue=-3.0)])["konkorde_signal"] == "Sharks selling"


def test_technical_legend_covers_the_three_indicators():
    terms = [term for term, _explanation in TECHNICAL_LEGEND_SECTIONS]
    assert len(terms) == 3
    assert any("RSI" in t for t in terms)
    assert any("MACD" in t for t in terms)
    assert any("Konkorde" in t for t in terms)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_technicals.py -v`
Expected: FAIL / collection error — `ModuleNotFoundError: No module named 'tools.technicals'`.

- [ ] **Step 3: Write the implementation**

Create `tools/technicals.py`:

```python
"""Technical indicators (RSI, MACD, Konkorde) computed from the daily
OHLCV rows in data/prices/<TICKER>.csv. Pure functions, no I/O: the
Sheet sync calls compute_indicators() at sync time, so nothing extra is
stored — every value can be re-derived from the price CSV."""

import math

import pandas as pd

RSI_PERIOD = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
KONKORDE_EMA = 15
KONKORDE_RANGE = 90
MFI_PERIOD = 14
BOLL_PERIOD = 25
BOLL_MULT = 2
STOCH_PERIOD = 21
CROSS_LOOKBACK = 3

INDICATOR_KEYS = [
    "rsi", "macd", "macd_signal", "macd_hist",
    "konkorde_green", "konkorde_brown", "konkorde_blue", "konkorde_avg",
]

TECHNICAL_LEGEND_SECTIONS = [
    (
        "RSI (Relative Strength Index)",
        "Momentum on a 0-100 scale over the last 14 trading days. Above 70 "
        "(red on Overview) = overbought: the price rose fast and may pause or "
        "pull back. Below 30 (green) = oversold: it fell fast and may bounce. "
        "In between is neutral. Each ticker tab charts it with the 70/30 lines "
        "dashed.",
    ),
    (
        "MACD (12, 26, 9)",
        "Trend-following momentum: the MACD line is the gap between a 12-day "
        "and a 26-day average of the price; the signal line is a 9-day average "
        "of the MACD line. \"Bullish\" = MACD above signal (upward momentum), "
        "\"Bearish\" = below. \"↑ cross\" / \"↓ cross\" = the two lines crossed "
        "within the last 3 trading days, the classic buy/sell trigger. On the "
        "ticker tab chart the green/red bars (histogram) are the distance "
        "between the two lines.",
    ),
    (
        "Konkorde",
        "Volume-based indicator (Blai5) that tries to separate who is moving "
        "the price. Blue = \"sharks\" (institutional money, read from days "
        "when volume falls - the negative volume index). Green = \"hands\" "
        "(retail/small investors). Brown = combined trend of RSI, money flow, "
        "Bollinger and stochastic; the red line is its 15-day average. "
        "\"Sharks buying\" on Overview = blue above zero. A classic read is "
        "blue rising above zero while green falls: institutions accumulating. "
        "Needs about 105 trading days of history before values appear.",
    ),
]


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def _wilder(values: pd.Series, period: int) -> pd.Series:
    """Wilder smoothing: seeded with the simple mean of the first `period`
    values (index 1..period, since index 0 is the NaN of a diff), then
    avg = (avg * (period - 1) + value) / period."""
    out = pd.Series(float("nan"), index=values.index)
    v = values.to_numpy(dtype=float)
    if len(v) <= period:
        return out
    avg = v[1:period + 1].mean()
    out.iloc[period] = avg
    for i in range(period + 1, len(v)):
        avg = (avg * (period - 1) + v[i]) / period
        out.iloc[i] = avg
    return out


def rsi(series: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = series.diff()
    avg_gain = _wilder(delta.clip(lower=0), period)
    avg_loss = _wilder((-delta).clip(lower=0), period)
    out = 100 - 100 / (1 + avg_gain / avg_loss)
    out[(avg_loss == 0) & (avg_gain > 0)] = 100.0
    out[(avg_loss == 0) & (avg_gain == 0)] = 50.0  # flat: neutral
    return out


def macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    line = _ema(close, MACD_FAST) - _ema(close, MACD_SLOW)
    signal = _ema(line, MACD_SIGNAL)
    return line, signal, line - signal


def _volume_index(tprice: pd.Series, volume: pd.Series, rising: bool) -> pd.Series:
    """Positive (rising=True) / negative (rising=False) volume index: starts
    at 1 and only moves, by the price's % change, on bars where volume rose
    (PVI) / fell (NVI) versus the previous bar."""
    t = tprice.to_numpy(dtype=float)
    v = volume.to_numpy(dtype=float)
    out: list[float] = []
    for i in range(len(t)):
        if i == 0:
            out.append(1.0)
            continue
        value = out[-1]
        moved = v[i] > v[i - 1] if rising else v[i] < v[i - 1]
        if moved and t[i - 1] != 0:
            value = value + (t[i] - t[i - 1]) / t[i - 1] * value
        out.append(value)
    return pd.Series(out, index=tprice.index, dtype=float)


def _range_oscillator(index_series: pd.Series) -> pd.Series:
    """(index - EMA15(index)) scaled by the EMA's 90-bar high-low range.
    A flat range gives NaN rather than a division by zero."""
    ema = _ema(index_series, KONKORDE_EMA)
    span = ema.rolling(KONKORDE_RANGE).max() - ema.rolling(KONKORDE_RANGE).min()
    return (index_series - ema) * 100 / span.where(span != 0)


def _mfi(tprice: pd.Series, volume: pd.Series, period: int = MFI_PERIOD) -> pd.Series:
    flow = tprice * volume
    change = tprice.diff()
    positive = flow.where(change > 0, 0.0).where(change.notna())
    negative = flow.where(change < 0, 0.0).where(change.notna())
    pos_sum = positive.rolling(period).sum()
    neg_sum = negative.rolling(period).sum()
    out = 100 - 100 / (1 + pos_sum / neg_sum)
    out[(neg_sum == 0) & (pos_sum > 0)] = 100.0
    out[(neg_sum == 0) & (pos_sum == 0)] = 50.0
    return out


def konkorde(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Blai5 Konkorde on numeric open/high/low/close/volume columns.
    Returns (green, brown, blue, avg)."""
    tprice = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
    oscp = _range_oscillator(_volume_index(tprice, df["volume"], rising=True))
    blue = _range_oscillator(_volume_index(tprice, df["volume"], rising=False))

    basis = tprice.rolling(BOLL_PERIOD).mean()
    dev = BOLL_MULT * tprice.rolling(BOLL_PERIOD).std(ddof=0)
    boll = (tprice - (basis - dev)) / (2 * dev).where(dev != 0) * 100

    lowest = df["low"].rolling(STOCH_PERIOD).min()
    highest = df["high"].rolling(STOCH_PERIOD).max()
    stoc = 100 * (tprice - lowest) / (highest - lowest).where(highest != lowest)

    brown = (rsi(tprice) + _mfi(tprice, df["volume"]) + boll + stoc / 3) / 2
    green = brown + oscp
    avg = _ema(brown, KONKORDE_EMA)
    return green, brown, blue, avg


def _clean(value) -> float | None:
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def compute_indicators(price_rows: list[dict]) -> list[dict]:
    """One dict per price row (sorted by date): {"date", *INDICATOR_KEYS},
    with None wherever an indicator is still warming up or undefined."""
    if not price_rows:
        return []
    df = pd.DataFrame(sorted(price_rows, key=lambda r: r["date"])).reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    line, signal, hist = macd(df["close"])
    green, brown, blue, avg = konkorde(df)
    series = {
        "rsi": rsi(df["close"]),
        "macd": line, "macd_signal": signal, "macd_hist": hist,
        "konkorde_green": green, "konkorde_brown": brown,
        "konkorde_blue": blue, "konkorde_avg": avg,
    }
    return [
        {"date": df["date"].iloc[i], **{key: _clean(series[key].iloc[i]) for key in INDICATOR_KEYS}}
        for i in range(len(df))
    ]


def latest_signals(indicator_rows: list[dict]) -> dict:
    """Latest-bar summary for the Overview tab."""
    result = {"rsi": None, "macd_signal": "", "konkorde_signal": ""}
    if not indicator_rows:
        return result
    last = indicator_rows[-1]
    result["rsi"] = last["rsi"]

    if last["macd"] is not None and last["macd_signal"] is not None:
        bullish = last["macd"] > last["macd_signal"]
        label = "Bullish" if bullish else "Bearish"
        for row in indicator_rows[-(CROSS_LOOKBACK + 1):-1]:
            if row["macd"] is None or row["macd_signal"] is None:
                continue
            if (row["macd"] > row["macd_signal"]) != bullish:
                label += " ↑ cross" if bullish else " ↓ cross"
                break
        result["macd_signal"] = label

    if last["konkorde_blue"] is not None:
        result["konkorde_signal"] = "Sharks buying" if last["konkorde_blue"] > 0 else "Sharks selling"
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_technicals.py -v`
Expected: all PASS. Then `python -m pytest -q` — whole suite still passes.

- [ ] **Step 5: Commit**

```bash
git add tools/technicals.py tests/test_technicals.py
git commit -m "feat: add RSI, MACD and Konkorde indicator engine

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: One-year default price lookback

**Files:**
- Modify: `tools/fetch_prices.py` (`compute_start_date`, the `default_lookback_days: int = 30` default)
- Test: `tests/test_fetch_prices.py`

**Interfaces:**
- Produces: `compute_start_date(ticker, default_lookback_days=365, today=None)` — same signature, new default.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fetch_prices.py` (it already imports `date` and `compute_start_date`; check the imports at the top and add any missing):

```python
def test_compute_start_date_default_lookback_is_one_year(tmp_path, monkeypatch):
    # Technical indicators (Konkorde needs ~105 bars) require a year of
    # history, so a brand-new holding fetches 365 days by default.
    monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path))
    start = compute_start_date("NEWCO", today=date(2026, 9, 18))
    assert start == date(2025, 9, 18)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fetch_prices.py -v`
Expected: the new test FAILS (`date(2026, 8, 19) != date(2025, 9, 18)`).

- [ ] **Step 3: Change the default**

In `tools/fetch_prices.py`, change the signature of `compute_start_date` to:

```python
def compute_start_date(ticker: str, default_lookback_days: int = 365, today: date | None = None) -> date:
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_fetch_prices.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/fetch_prices.py tests/test_fetch_prices.py
git commit -m "feat: fetch a year of prices for new holdings

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Ticker tab layout + chart requests (`tools/ticker_tab.py`)

**Files:**
- Create: `tools/ticker_tab.py`
- Test: `tests/test_ticker_tab.py`

**Interfaces:**
- Consumes (Task 1): `compute_indicators(price_rows)` output shape — list of `{"date": str, "rsi", "macd", "macd_signal", "macd_hist", "konkorde_green", "konkorde_brown", "konkorde_blue", "konkorde_avg"}` with `float | None` values.
- Produces:
  - `TICKER_TAB_HEADER: list[str]` (15 columns, see code), `HELPER_COLUMNS: list[str]`, `CHART_WINDOW_ROWS = 126`, `CHART_ANCHOR_COL = 15`, `TAB_MIN_COLS = 16`, `CHART_COLORS: dict[str, str]`.
  - `hex_to_rgb_fraction(hex_color: str) -> dict` (moved here from `sync_google_sheet._hex_to_rgb_fraction`; Task 4 re-points the import).
  - `build_ticker_tab_rows(price_rows: list[dict], news_entries: list[dict], indicator_rows: list[dict]) -> list[list]`
  - `existing_chart_ids(metadata: dict, sheet_id: int) -> list[int]` — `metadata` is `spreadsheet.fetch_sheet_metadata()`.
  - `build_chart_requests(sheet_id: int, row_count: int, existing_ids: list[int]) -> list[dict]` — one list for a single `spreadsheet.batch_update({"requests": ...})`: deletes old charts, freezes the header row, hides helper columns, adds 4 charts.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ticker_tab.py`:

```python
from tools.ticker_tab import (
    CHART_ANCHOR_COL,
    CHART_WINDOW_ROWS,
    HELPER_COLUMNS,
    TAB_MIN_COLS,
    TICKER_TAB_HEADER,
    build_chart_requests,
    build_ticker_tab_rows,
    existing_chart_ids,
    hex_to_rgb_fraction,
)
from tools.technicals import INDICATOR_KEYS


def _indicator(date, **values):
    row = {"date": date, **{k: None for k in INDICATOR_KEYS}}
    row.update(values)
    return row


def test_header_has_visible_columns_then_hidden_helpers_last():
    assert TICKER_TAB_HEADER[:11] == [
        "Date", "Close", "RSI", "MACD", "Signal", "Histogram",
        "Konkorde Green", "Konkorde Brown", "Konkorde Blue", "Konkorde Avg", "News",
    ]
    assert TICKER_TAB_HEADER[-len(HELPER_COLUMNS):] == HELPER_COLUMNS
    assert CHART_ANCHOR_COL == len(TICKER_TAB_HEADER)
    assert TAB_MIN_COLS == CHART_ANCHOR_COL + 1


def test_build_ticker_tab_rows_numbers_news_and_blanks():
    price_rows = [
        {"date": "2026-09-16", "close": "163.9"},
        {"date": "2026-09-15", "close": "160.0"},
    ]
    news = [{"date": "2026-09-16", "title": "Honeywell raises guidance", "url": "https://x", "source": "Reuters", "fetched_at": "now"}]
    indicators = [
        _indicator("2026-09-15"),
        _indicator("2026-09-16", rsi=61.23456, macd=1.234567, macd_signal=1.0, macd_hist=0.234567,
                   konkorde_green=12.346, konkorde_brown=40.0, konkorde_blue=-5.5, konkorde_avg=38.0),
    ]

    rows = build_ticker_tab_rows(price_rows, news, indicators)

    assert rows[0] == TICKER_TAB_HEADER
    # warm-up row: numbers blank, helper bands still present, sorted by date
    assert rows[1] == ["2026-09-15", 160.0, "", "", "", "", "", "", "", "", "", 70, 30, "", ""]
    assert rows[2] == [
        "2026-09-16", 163.9, 61.23, 1.2346, 1.0, 0.2346,
        12.35, 40.0, -5.5, 38.0, "Honeywell raises guidance",
        70, 30, 0.2346, "",
    ]


def test_negative_histogram_goes_to_hist_minus_column():
    rows = build_ticker_tab_rows(
        [{"date": "2026-09-16", "close": "10"}], [], [_indicator("2026-09-16", macd_hist=-0.5)]
    )
    assert rows[1][TICKER_TAB_HEADER.index("Hist +")] == ""
    assert rows[1][TICKER_TAB_HEADER.index("Hist -")] == -0.5


def test_existing_chart_ids_only_for_that_sheet():
    metadata = {"sheets": [
        {"properties": {"sheetId": 1}, "charts": [{"chartId": 11}, {"chartId": 12}]},
        {"properties": {"sheetId": 2}},
    ]}
    assert existing_chart_ids(metadata, 1) == [11, 12]
    assert existing_chart_ids(metadata, 2) == []
    assert existing_chart_ids(metadata, 99) == []


def _add_chart_specs(requests):
    return [r["addChart"]["chart"]["spec"] for r in requests if "addChart" in r]


def test_build_chart_requests_replaces_charts_hides_helpers_and_freezes():
    requests = build_chart_requests(sheet_id=7, row_count=251, existing_ids=[11, 12])

    deletes = [r["deleteEmbeddedObject"]["objectId"] for r in requests if "deleteEmbeddedObject" in r]
    assert deletes == [11, 12]
    # deletes come before the new charts are added
    first_add = next(i for i, r in enumerate(requests) if "addChart" in r)
    assert all("deleteEmbeddedObject" not in r for r in requests[first_add:])

    hide = next(r["updateDimensionProperties"] for r in requests if "updateDimensionProperties" in r)
    assert hide["range"] == {
        "sheetId": 7, "dimension": "COLUMNS",
        "startIndex": TICKER_TAB_HEADER.index(HELPER_COLUMNS[0]),
        "endIndex": len(TICKER_TAB_HEADER),
    }
    assert hide["properties"] == {"hiddenByUser": True}

    freeze = next(r["updateSheetProperties"] for r in requests if "updateSheetProperties" in r)
    assert freeze["properties"]["gridProperties"]["frozenRowCount"] == 1

    titles = [s["title"] for s in _add_chart_specs(requests)]
    assert titles == ["Price (Close)", "MACD (12, 26, 9)", "RSI (14)", "Konkorde"]


def test_charts_plot_hidden_helpers_and_stack_to_the_right():
    requests = build_chart_requests(sheet_id=7, row_count=251, existing_ids=[])
    adds = [r["addChart"]["chart"] for r in requests if "addChart" in r]

    rows = []
    for chart in adds:
        assert chart["spec"]["hiddenDimensionStrategy"] == "SHOW_ALL"
        anchor = chart["position"]["overlayPosition"]["anchorCell"]
        assert anchor["sheetId"] == 7 and anchor["columnIndex"] == CHART_ANCHOR_COL
        rows.append(anchor["rowIndex"])
    assert rows == sorted(rows) and len(set(rows)) == 4


def test_chart_series_use_header_row_plus_last_window_rows():
    requests = build_chart_requests(sheet_id=7, row_count=251, existing_ids=[])
    spec = _add_chart_specs(requests)[0]["basicChart"]
    sources = spec["domains"][0]["domain"]["sourceRange"]["sources"]

    assert spec["headerCount"] == 1
    assert sources[0]["startRowIndex"] == 0 and sources[0]["endRowIndex"] == 1
    assert sources[1]["startRowIndex"] == 251 - CHART_WINDOW_ROWS
    assert sources[1]["endRowIndex"] == 251


def test_short_tab_uses_one_contiguous_range():
    requests = build_chart_requests(sheet_id=7, row_count=30, existing_ids=[])
    sources = _add_chart_specs(requests)[0]["basicChart"]["domains"][0]["domain"]["sourceRange"]["sources"]
    assert len(sources) == 1
    assert sources[0]["startRowIndex"] == 0 and sources[0]["endRowIndex"] == 30


def _series_columns(spec):
    return [
        TICKER_TAB_HEADER[s["series"]["sourceRange"]["sources"][-1]["startColumnIndex"]]
        for s in spec["basicChart"]["series"]
    ]


def test_each_chart_plots_the_right_columns():
    specs = _add_chart_specs(build_chart_requests(sheet_id=7, row_count=251, existing_ids=[]))

    assert _series_columns(specs[0]) == ["Close"]
    assert _series_columns(specs[1]) == ["Hist +", "Hist -", "MACD", "Signal"]
    assert _series_columns(specs[2]) == ["RSI", "RSI 70", "RSI 30"]
    assert _series_columns(specs[3]) == ["Konkorde Green", "Konkorde Brown", "Konkorde Blue", "Konkorde Avg"]
    assert [s["type"] for s in specs[1]["basicChart"]["series"]] == ["COLUMN", "COLUMN", "LINE", "LINE"]
    assert [s["type"] for s in specs[3]["basicChart"]["series"]] == ["AREA", "AREA", "AREA", "LINE"]


def test_rsi_chart_axis_fixed_0_to_100():
    spec = _add_chart_specs(build_chart_requests(sheet_id=7, row_count=251, existing_ids=[]))[2]
    left = next(a for a in spec["basicChart"]["axis"] if a["position"] == "LEFT_AXIS")
    assert left["viewWindowOptions"] == {"viewWindowMin": 0, "viewWindowMax": 100, "viewWindowMode": "EXPLICIT"}


def test_hex_to_rgb_fraction():
    assert hex_to_rgb_fraction("#ff0000") == {"red": 1.0, "green": 0.0, "blue": 0.0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ticker_tab.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'tools.ticker_tab'`.

- [ ] **Step 3: Write the implementation**

Create `tools/ticker_tab.py`:

```python
"""One Sheet tab per ticker: daily close + technical indicator columns,
and the native Sheets charts (Price, MACD, RSI, Konkorde) drawn from
them. Pure functions returning rows / batch_update requests — the Google
calls themselves live in sync_google_sheet."""

TICKER_TAB_HEADER = [
    "Date", "Close", "RSI", "MACD", "Signal", "Histogram",
    "Konkorde Green", "Konkorde Brown", "Konkorde Blue", "Konkorde Avg", "News",
    # Hidden helpers the charts need: flat 70/30 RSI bands, and the MACD
    # histogram split by sign so it can render as green/red columns.
    "RSI 70", "RSI 30", "Hist +", "Hist -",
]
HELPER_COLUMNS = ["RSI 70", "RSI 30", "Hist +", "Hist -"]

CHART_WINDOW_ROWS = 126  # ~6 months of trading days
CHART_ANCHOR_COL = len(TICKER_TAB_HEADER)  # charts sit just right of the helpers
TAB_MIN_COLS = CHART_ANCHOR_COL + 1  # an overlay's anchor cell must exist in the grid
CHART_ROW_SPACING = 17
CHART_WIDTH_PX = 900
CHART_HEIGHT_PX = 320

# Validated colorblind-safe with the dataviz palette validator.
CHART_COLORS = {
    "up": "#2ea36b",
    "down": "#d64545",
    "primary": "#2f6fd6",
    "secondary": "#c96a12",
    "konkorde_green": "#2ea36b",
    "konkorde_brown": "#a0522d",
    "konkorde_blue": "#2f6fd6",
    "konkorde_avg": "#d64545",
    "band": "#9e9e9e",
}


def hex_to_rgb_fraction(hex_color: str) -> dict:
    hex_color = hex_color.lstrip("#")
    return {
        "red": int(hex_color[0:2], 16) / 255,
        "green": int(hex_color[2:4], 16) / 255,
        "blue": int(hex_color[4:6], 16) / 255,
    }


def _num(value: float | None, digits: int = 4):
    return "" if value is None else round(value, digits)


def build_ticker_tab_rows(price_rows: list[dict], news_entries: list[dict], indicator_rows: list[dict]) -> list[list]:
    news_by_date: dict[str, list[str]] = {}
    for n in news_entries:
        news_by_date.setdefault(n["date"], []).append(n["title"])
    indicators_by_date = {r["date"]: r for r in indicator_rows}

    rows = [TICKER_TAB_HEADER]
    for p in sorted(price_rows, key=lambda r: r["date"]):
        ind = indicators_by_date.get(p["date"], {})
        hist = ind.get("macd_hist")
        rows.append([
            p["date"], round(float(p["close"]), 4),
            _num(ind.get("rsi"), 2),
            _num(ind.get("macd")), _num(ind.get("macd_signal")), _num(hist),
            _num(ind.get("konkorde_green"), 2), _num(ind.get("konkorde_brown"), 2),
            _num(ind.get("konkorde_blue"), 2), _num(ind.get("konkorde_avg"), 2),
            "; ".join(news_by_date.get(p["date"], [])),
            70, 30,
            _num(hist) if hist is not None and hist >= 0 else "",
            _num(hist) if hist is not None and hist < 0 else "",
        ])
    return rows


def existing_chart_ids(metadata: dict, sheet_id: int) -> list[int]:
    for sheet in metadata.get("sheets", []):
        if sheet["properties"]["sheetId"] == sheet_id:
            return [c["chartId"] for c in sheet.get("charts", [])]
    return []


def _col(name: str) -> int:
    return TICKER_TAB_HEADER.index(name)


def _grid_range(sheet_id: int, col: int, start_row: int, end_row: int) -> dict:
    return {
        "sheetId": sheet_id,
        "startRowIndex": start_row, "endRowIndex": end_row,
        "startColumnIndex": col, "endColumnIndex": col + 1,
    }


def _chart_data(sheet_id: int, col: int, row_count: int) -> dict:
    """Header row + the last CHART_WINDOW_ROWS data rows. When the tab is
    longer than the window, the header is its own source range so the
    chart still names each series from row 1 (headerCount=1)."""
    start = max(1, row_count - CHART_WINDOW_ROWS)
    if start == 1:
        sources = [_grid_range(sheet_id, col, 0, row_count)]
    else:
        sources = [_grid_range(sheet_id, col, 0, 1), _grid_range(sheet_id, col, start, row_count)]
    return {"sourceRange": {"sources": sources}}


def _series(sheet_id: int, column: str, row_count: int, series_type: str, color: str, dashed: bool = False) -> dict:
    series = {
        "series": _chart_data(sheet_id, _col(column), row_count),
        "targetAxis": "LEFT_AXIS",
        "type": series_type,
        "colorStyle": {"rgbColor": hex_to_rgb_fraction(CHART_COLORS[color])},
    }
    if series_type == "LINE":
        series["lineStyle"] = {"type": "MEDIUM_DASHED", "width": 1} if dashed else {"type": "SOLID", "width": 2}
    return series


def _add_chart(sheet_id: int, row_count: int, slot: int, title: str, chart_type: str,
               series: list[dict], legend: str = "BOTTOM_LEGEND", left_axis: dict | None = None) -> dict:
    left = {"position": "LEFT_AXIS", **(left_axis or {})}
    return {
        "addChart": {
            "chart": {
                "spec": {
                    "title": title,
                    # Helper columns are hidden; without SHOW_ALL Sheets
                    # silently drops hidden columns from charts.
                    "hiddenDimensionStrategy": "SHOW_ALL",
                    "basicChart": {
                        "chartType": chart_type,
                        "legendPosition": legend,
                        "headerCount": 1,
                        "axis": [{"position": "BOTTOM_AXIS"}, left],
                        "domains": [{"domain": _chart_data(sheet_id, _col("Date"), row_count)}],
                        "series": series,
                    },
                },
                "position": {
                    "overlayPosition": {
                        "anchorCell": {
                            "sheetId": sheet_id,
                            "rowIndex": slot * CHART_ROW_SPACING,
                            "columnIndex": CHART_ANCHOR_COL,
                        },
                        "widthPixels": CHART_WIDTH_PX,
                        "heightPixels": CHART_HEIGHT_PX,
                    }
                },
            }
        }
    }


def build_chart_requests(sheet_id: int, row_count: int, existing_ids: list[int]) -> list[dict]:
    """Everything a ticker tab needs after its values are written, as one
    batch_update: drop the previous sync's charts (so they don't pile up),
    freeze the header, hide the helper columns, add the 4 charts."""
    requests: list[dict] = [{"deleteEmbeddedObject": {"objectId": chart_id}} for chart_id in existing_ids]

    requests.append({
        "updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount",
        }
    })
    first_helper = _col(HELPER_COLUMNS[0])
    requests.append({
        "updateDimensionProperties": {
            "range": {
                "sheetId": sheet_id, "dimension": "COLUMNS",
                "startIndex": first_helper, "endIndex": first_helper + len(HELPER_COLUMNS),
            },
            "properties": {"hiddenByUser": True},
            "fields": "hiddenByUser",
        }
    })

    s = lambda column, series_type, color, dashed=False: _series(sheet_id, column, row_count, series_type, color, dashed)
    requests += [
        _add_chart(sheet_id, row_count, 0, "Price (Close)", "LINE",
                   [s("Close", "LINE", "primary")], legend="NO_LEGEND"),
        _add_chart(sheet_id, row_count, 1, "MACD (12, 26, 9)", "COMBO", [
            s("Hist +", "COLUMN", "up"),
            s("Hist -", "COLUMN", "down"),
            s("MACD", "LINE", "primary"),
            s("Signal", "LINE", "secondary"),
        ]),
        _add_chart(sheet_id, row_count, 2, "RSI (14)", "LINE", [
            s("RSI", "LINE", "primary"),
            s("RSI 70", "LINE", "band", dashed=True),
            s("RSI 30", "LINE", "band", dashed=True),
        ], left_axis={"viewWindowOptions": {"viewWindowMin": 0, "viewWindowMax": 100, "viewWindowMode": "EXPLICIT"}}),
        _add_chart(sheet_id, row_count, 3, "Konkorde", "COMBO", [
            s("Konkorde Green", "AREA", "konkorde_green"),
            s("Konkorde Brown", "AREA", "konkorde_brown"),
            s("Konkorde Blue", "AREA", "konkorde_blue"),
            s("Konkorde Avg", "LINE", "konkorde_avg"),
        ]),
    ]
    return requests
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ticker_tab.py -v`
Expected: all PASS. Then `python -m pytest -q` — whole suite passes.

- [ ] **Step 5: Commit**

```bash
git add tools/ticker_tab.py tests/test_ticker_tab.py
git commit -m "feat: ticker tab indicator layout and native chart requests

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Wire technicals into the Sheet sync (Overview, Legend, ticker tabs, backoff)

**Files:**
- Modify: `tools/sync_google_sheet.py`
- Modify: `tests/test_sync_google_sheet.py`

**Interfaces:**
- Consumes (Task 1): `compute_indicators`, `latest_signals`, `TECHNICAL_LEGEND_SECTIONS` from `tools.technicals`.
- Consumes (Task 3): `TAB_MIN_COLS`, `build_chart_requests`, `build_ticker_tab_rows`, `existing_chart_ids`, `hex_to_rgb_fraction` from `tools.ticker_tab`.
- Produces:
  - `OVERVIEW_HEADER` gains `"RSI", "MACD", "Konkorde"` directly before `"P/E"`.
  - `build_overview_rows(holdings, latest_history, latest_fundamentals, latest_analysis, latest_technicals: dict[str, dict] | None = None)` — `latest_technicals[ticker]` is a `latest_signals()` dict.
  - `build_legend_rows()` = header + `LEGEND_SECTIONS` rows + `TECHNICAL_LEGEND_SECTIONS` rows.
  - `_rsi_format_requests(sheet_id, col_index, row_count) -> list[dict]`, `_signal_text_format_requests(sheet_id, col_index, row_count, positive_prefix, negative_prefix) -> list[dict]`.

- [ ] **Step 1: Update and add the failing tests**

In `tests/test_sync_google_sheet.py`:

1. Change the import block at the top to (drops `build_ticker_tab_rows`, which moved to `tools.ticker_tab` and is tested in `tests/test_ticker_tab.py`; adds the new helpers):

```python
from tools.sync_google_sheet import (
    LEGEND_HEADER,
    OVERVIEW_HEADER,
    _column_letter,
    _delta_format_requests,
    _rating_format_requests,
    _rsi_format_requests,
    _score_format_requests,
    _signal_text_format_requests,
    build_legend_rows,
    build_overview_rows,
)
```

2. Delete the whole `test_build_ticker_tab_rows_joins_news_by_date` function.

3. Replace `test_build_legend_rows_covers_every_documented_term` with:

```python
def test_build_legend_rows_covers_every_documented_term():
    from tools.scoring import LEGEND_SECTIONS
    from tools.technicals import TECHNICAL_LEGEND_SECTIONS

    rows = build_legend_rows()

    assert rows[0] == LEGEND_HEADER
    expected = LEGEND_SECTIONS + TECHNICAL_LEGEND_SECTIONS
    assert len(rows) == len(expected) + 1
    assert [row[0] for row in rows[1:]] == [term for term, _explanation in expected]
```

4. Append these new tests:

```python
_MMM_HOLDING = {"ticker": "HON", "company": "Honeywell International", "shares": 10, "currency": "USD", "avg_cost_local": 120.50, "is_etf": False}
_MMM_HISTORY = {"HON": {"price_local": "163.90", "value_eur": "1500.00", "gp_eur": "250.00", "gp_pct": "20.00", "date": "2026-09-16"}}


def test_overview_header_has_technical_columns_before_pe():
    i = OVERVIEW_HEADER.index("RSI")
    assert OVERVIEW_HEADER[i:i + 4] == ["RSI", "MACD", "Konkorde", "P/E"]


def test_build_overview_rows_includes_latest_technical_signals():
    technicals = {"HON": {"rsi": 72.345, "macd_signal": "Bullish ↑ cross", "konkorde_signal": "Sharks buying"}}

    rows = build_overview_rows([_MMM_HOLDING], _MMM_HISTORY, {}, {}, technicals)

    row = dict(zip(OVERVIEW_HEADER, rows[1]))
    assert row["RSI"] == 72.3
    assert row["MACD"] == "Bullish ↑ cross"
    assert row["Konkorde"] == "Sharks buying"


def test_build_overview_rows_technicals_blank_when_missing():
    rows = build_overview_rows([_MMM_HOLDING], _MMM_HISTORY, {}, {})

    row = dict(zip(OVERVIEW_HEADER, rows[1]))
    assert row["RSI"] == "" and row["MACD"] == "" and row["Konkorde"] == ""


def test_rsi_format_requests_overbought_red_oversold_green():
    from tools.scoring import DELTA_DOWN_COLOR, DELTA_UP_COLOR
    from tools.ticker_tab import hex_to_rgb_fraction

    requests = _rsi_format_requests(sheet_id=3, col_index=5, row_count=10)
    rules = [r["addConditionalFormatRule"]["rule"]["booleanRule"] for r in requests]

    by_condition = {(b["condition"]["type"], b["condition"]["values"][0]["userEnteredValue"]): b["format"] for b in rules}
    assert by_condition[("NUMBER_GREATER", "70")]["textFormat"]["foregroundColor"] == hex_to_rgb_fraction(DELTA_DOWN_COLOR)
    assert by_condition[("NUMBER_LESS", "30")]["textFormat"]["foregroundColor"] == hex_to_rgb_fraction(DELTA_UP_COLOR)


def test_signal_text_format_requests_match_by_prefix():
    requests = _signal_text_format_requests(sheet_id=3, col_index=5, row_count=10,
                                            positive_prefix="Bullish", negative_prefix="Bearish")
    conditions = [r["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"] for r in requests]
    assert [(c["type"], c["values"][0]["userEnteredValue"]) for c in conditions] == [
        ("TEXT_STARTS_WITH", "Bullish"), ("TEXT_STARTS_WITH", "Bearish"),
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sync_google_sheet.py -v`
Expected: ImportError on `_rsi_format_requests` / `_signal_text_format_requests`.

- [ ] **Step 3: Implement the changes in `tools/sync_google_sheet.py`**

3a. Imports — add below the existing `from tools.scoring import (...)` block:

```python
from gspread.http_client import BackOffHTTPClient

from tools.technicals import TECHNICAL_LEGEND_SECTIONS, compute_indicators, latest_signals
from tools.ticker_tab import (
    TAB_MIN_COLS,
    build_chart_requests,
    build_ticker_tab_rows,
    existing_chart_ids,
    hex_to_rgb_fraction as _hex_to_rgb_fraction,
)
```

and delete the local `def _hex_to_rgb_fraction(...)` function (the aliased import keeps every existing call site working).

3b. Overview header — replace the line `OVERVIEW_HEADER += ["P/E", "Div Yield", "Last Updated"]` with:

```python
TECHNICAL_COLUMNS = ["RSI", "MACD", "Konkorde"]
OVERVIEW_HEADER += TECHNICAL_COLUMNS
OVERVIEW_HEADER += ["P/E", "Div Yield", "Last Updated"]
```

and delete the now-unused `TICKER_TAB_HEADER = ["Date", "Close", "News"]` line.

3c. `build_overview_rows` — new signature and the technical cells just before P/E:

```python
def build_overview_rows(holdings: list[dict], latest_history: dict[str, dict], latest_fundamentals: dict[str, dict], latest_analysis: dict[str, dict], latest_technicals: dict[str, dict] | None = None) -> list[list]:
```

Inside the loop, replace `row += [fund.get("pe_ratio", ""), fund.get("dividend_yield", ""), hist.get("date", "")]` with:

```python
        tech = (latest_technicals or {}).get(h["ticker"], {})
        rsi_value = tech.get("rsi")
        row += [
            "" if rsi_value is None else round(rsi_value, 1),
            tech.get("macd_signal", ""),
            tech.get("konkorde_signal", ""),
        ]
        row += [fund.get("pe_ratio", ""), fund.get("dividend_yield", ""), hist.get("date", "")]
```

3d. `build_legend_rows` — iterate both lists:

```python
    for term, explanation in LEGEND_SECTIONS + TECHNICAL_LEGEND_SECTIONS:
        rows.append([term, explanation])
```

and add one sentence to its docstring: technical-indicator rows are Sheet-only (the Doc legend uses `LEGEND_SECTIONS` alone).

3e. Delete the old `build_ticker_tab_rows` function from this file (it now lives in `tools/ticker_tab.py`).

3f. New formatting helpers, placed after `_rating_format_requests`:

```python
def _column_range(sheet_id: int, col_index: int, row_count: int) -> dict:
    return {
        "sheetId": sheet_id,
        "startRowIndex": 1, "endRowIndex": row_count,
        "startColumnIndex": col_index, "endColumnIndex": col_index + 1,
    }


def _text_color_rule(value_range: dict, condition_type: str, value: str, hex_color: str) -> dict:
    return {
        "addConditionalFormatRule": {
            "rule": {
                "ranges": [value_range],
                "booleanRule": {
                    "condition": {"type": condition_type, "values": [{"userEnteredValue": value}]},
                    "format": {"textFormat": {"foregroundColor": _hex_to_rgb_fraction(hex_color), "bold": True}},
                },
            },
            "index": 0,
        }
    }


def _rsi_format_requests(sheet_id: int, col_index: int, row_count: int) -> list[dict]:
    """RSI > 70 red (overbought), < 30 green (oversold); the two conditions
    can never both hold, so rule order doesn't matter."""
    value_range = _column_range(sheet_id, col_index, row_count)
    return [
        _text_color_rule(value_range, "NUMBER_GREATER", "70", DELTA_DOWN_COLOR),
        _text_color_rule(value_range, "NUMBER_LESS", "30", DELTA_UP_COLOR),
    ]


def _signal_text_format_requests(sheet_id: int, col_index: int, row_count: int, positive_prefix: str, negative_prefix: str) -> list[dict]:
    """Green/red text for the MACD ("Bullish…"/"Bearish…") and Konkorde
    ("Sharks buying"/"Sharks selling") signal columns."""
    value_range = _column_range(sheet_id, col_index, row_count)
    return [
        _text_color_rule(value_range, "TEXT_STARTS_WITH", positive_prefix, DELTA_UP_COLOR),
        _text_color_rule(value_range, "TEXT_STARTS_WITH", negative_prefix, DELTA_DOWN_COLOR),
    ]
```

3g. `apply_overview_formatting` — before `if requests:` add:

```python
    requests += _rsi_format_requests(sheet_id, OVERVIEW_HEADER.index("RSI"), row_count)
    requests += _signal_text_format_requests(sheet_id, OVERVIEW_HEADER.index("MACD"), row_count, "Bullish", "Bearish")
    requests += _signal_text_format_requests(sheet_id, OVERVIEW_HEADER.index("Konkorde"), row_count, "Sharks buying", "Sharks selling")
```

and extend its docstring with: "…plus the RSI (overbought red / oversold green) and MACD / Konkorde signal columns (green/red text)."

3h. `write_sheet` — replace the ticker-tab loop (from `existing_titles = {ws.title for ws in spreadsheet.worksheets()}` to the end of the function) with:

```python
    existing_titles = {ws.title for ws in spreadsheet.worksheets()}
    # One metadata read for the whole sync (chart IDs per tab), rather than
    # one per tab — keeps us well inside the Sheets per-minute quota.
    metadata = spreadsheet.fetch_sheet_metadata()
    for ticker, rows in ticker_tabs.items():
        if ticker in existing_titles:
            ws = spreadsheet.worksheet(ticker)
            ws.clear()
            # ws.clear() does not resize the grid, so a tab whose price
            # history has grown past its current row count would silently
            # lose an update() call without this — resize to at least fit.
            # Columns: the indicator layout plus the charts' anchor column.
            ws.resize(rows=max(len(rows), ws.row_count), cols=max(TAB_MIN_COLS, ws.col_count))
        else:
            ws = spreadsheet.add_worksheet(title=ticker, rows=max(len(rows), 100), cols=TAB_MIN_COLS)
        ws.update(rows)
        spreadsheet.batch_update({"requests": build_chart_requests(ws.id, len(rows), existing_chart_ids(metadata, ws.id))})
```

3i. `main` — replace the section from `overview_rows = build_overview_rows(...)` through the ticker-tab loop and the `client = gspread.authorize(...)` line with:

```python
    ticker_tabs = {}
    latest_technicals = {}
    for h in holdings:
        price_rows = load_csv_rows(price_csv_path(h["ticker"]))
        news_entries = load_jsonl_rows(news_jsonl_path(h["ticker"]))
        indicators = compute_indicators(price_rows)
        latest_technicals[h["ticker"]] = latest_signals(indicators)
        if price_rows:
            ticker_tabs[h["ticker"]] = build_ticker_tab_rows(price_rows, news_entries, indicators)

    overview_rows = build_overview_rows(holdings, latest_history, latest_fundamentals, latest_analysis, latest_technicals)

    # BackOffHTTPClient retries 429 "quota exceeded" responses with
    # exponential backoff: 15 ticker tabs x (clear, resize, update, charts)
    # plus the other tabs is close to Sheets' ~60 writes/minute limit.
    client = gspread.authorize(get_credentials(), http_client=BackOffHTTPClient)
```

(the `spreadsheet = get_or_create_spreadsheet(client)` line and everything after it stay as they are).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q`
Expected: whole suite PASSES (including the previously existing Overview tests — `rows[1][5]` is still "Value (EUR)").
Also run: `python -c "import tools.sync_google_sheet"` — imports cleanly.

- [ ] **Step 5: Commit**

```bash
git add tools/sync_google_sheet.py tests/test_sync_google_sheet.py
git commit -m "feat: technical indicators and charts in the Sheet sync

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Backfill, live verification, workflow docs (controller — not a subagent)

This task touches real data, Google auth and the owner's live Sheet; the orchestrating agent does it directly.

**Files:**
- Modify: `workflows/update_portfolio.md`, `workflows/add_holding.md`
- Data (gitignored, disposable per CLAUDE.md): `data/prices/*.csv`

- [ ] **Step 1: Backfill one year of prices for every holding**

For each ticker in `data/portfolio.yaml` (read via `python -c "from tools.portfolio_lib import load_portfolio; print(' '.join(h['ticker'] for h in load_portfolio()))"`):

```bash
python -m tools.fetch_prices --ticker <TICKER> --start 2025-09-18
```

Expected per ticker: `fetched ~250 days, ~225 new`. Then confirm each CSV has ≥ 240 rows (`wc -l data/prices/*.csv`).

- [ ] **Step 2: Sanity-check indicators on real data**

```bash
python -c "from tools.portfolio_lib import load_csv_rows; from tools.fetch_prices import price_csv_path; from tools.technicals import compute_indicators, latest_signals; r=compute_indicators(load_csv_rows(price_csv_path('ABBV'))); print(r[-1]); print(latest_signals(r))"
```

Expected: all 8 values non-None and finite on the last row; RSI in 0-100.

- [ ] **Step 3: Live sync**

Run: `python -m tools.sync_google_sheet`
Expected: `Synced N holdings to Google Sheet: <url>`.
If the API rejects the two-range (header + window) chart sources: switch `_chart_data` in `tools/ticker_tab.py` to always use one contiguous range `0..row_count` (full year), update `test_chart_series_use_header_row_plus_last_window_rows` accordingly, rerun tests, and record the finding in `workflows/update_portfolio.md` Notes.

- [ ] **Step 4: Visual check**

Open the Sheet and confirm on at least ABBV and NOVN.SW: 4 charts stacked right of the data, green/red MACD histogram, RSI with dashed 70/30 bands on a 0-100 axis, Konkorde areas + red average line, helper columns hidden, header frozen. Re-run the sync once more and confirm there are still exactly 4 charts per tab (no pile-up). Confirm the Overview RSI/MACD/Konkorde columns and colors, and the 3 new Legend rows.

- [ ] **Step 5: Update workflows**

`workflows/update_portfolio.md`:
- In **Deliverable format**, add a paragraph: every ticker tab shows RSI(14), MACD(12,26,9) and Konkorde columns with 4 native charts (Price, MACD, RSI, Konkorde; last ~6 months), computed by `tools/technicals.py` at sync time from `data/prices/<TICKER>.csv` — no agent input needed; the Overview tab shows the latest RSI / MACD / Konkorde signal per holding. These don't affect Rating.
- In **Notes for future refinement**, add a dated (2026-09-18) note: price CSVs were backfilled to one year with `fetch_prices --start 2025-09-18`; `compute_start_date` now defaults to 365 days; Konkorde needs ~105 trading days before values appear; any live-sync quirks found in Step 3/4.

`workflows/add_holding.md`: next to the `fetch_prices` step, note that the first fetch pulls a year of history (the technical charts need ~105 trading days before Konkorde shows values).

- [ ] **Step 6: Final check and commit**

Run: `python -m pytest -q` — all pass.

```bash
git add workflows/update_portfolio.md workflows/add_holding.md tools/ticker_tab.py tests/test_ticker_tab.py
git commit -m "docs: document technical analysis tabs and one-year price backfill

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```
