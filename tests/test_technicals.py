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


def test_volume_index_hand_computed_oracle():
    # Hand derivation (PVI starts at 1 and only moves, by tprice's % change,
    # on bars where volume ROSE vs. the previous bar; NVI only on bars where
    # volume FELL; a tied volume bar moves neither):
    #
    #   i  tprice  volume   vs prev        PVI                      NVI
    #   0    10      100      seed         1.0                      1.0
    #   1    11      150    rose (150>100) 1 + (11-10)/10*1 = 1.1    unchanged: 1.0
    #   2     9       90    fell (90<150)  unchanged: 1.1            1 + (9-11)/11*1 = 1 - 2/11 = 9/11
    #   3     9       90    tied (90==90)  unchanged: 1.1            unchanged: 9/11
    tprice = pd.Series([10.0, 11.0, 9.0, 9.0])
    volume = pd.Series([100.0, 150.0, 90.0, 90.0])

    pvi = _volume_index(tprice, volume, rising=True)
    nvi = _volume_index(tprice, volume, rising=False)

    assert pvi.tolist() == pytest.approx([1.0, 1.1, 1.1, 1.1])
    assert nvi.tolist() == pytest.approx([1.0, 1.0, 9 / 11, 9 / 11])


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


def test_latest_signals_flat_macd_equals_signal_is_neither_bullish_nor_bearish():
    # Exactly-equal MACD/signal (both 0.0 on flat/degenerate data) must not
    # fall through the strict `>` into "Bearish" — treated like "not enough
    # data" (blank), not a signal.
    assert latest_signals([_row(0.0, 0.0)])["macd_signal"] == ""
    # Still detects a real cross into a flat tail: the label is decided by
    # the last bar (equal -> blank), so an approaching-but-not-yet-equal
    # bullish state stays "Bullish" up to the point they coincide.
    assert latest_signals([_row(2, 1), _row(0.0, 0.0)])["macd_signal"] == ""


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
