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
        if last["macd"] == last["macd_signal"]:
            # Exactly-equal MACD/signal (e.g. both 0.0 on flat/degenerate
            # data) is neither bullish nor bearish — cosmetic on real prices,
            # but a strict `>` would otherwise fall through to "Bearish".
            result["macd_signal"] = ""
        else:
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
