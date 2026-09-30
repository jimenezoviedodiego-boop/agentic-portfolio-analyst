from datetime import date
from pathlib import Path

from tools.fetch_fundamentals import latest_fundamentals_snapshot
from tools.fetch_fx_rate import get_rate
from tools.fetch_prices import price_csv_path
from tools.portfolio_lib import append_dedup_csv, data_dir, latest_by_date, load_csv_rows, load_portfolio
from tools.portfolio_math import compute_value_and_gp
from tools.scoring import (
    compute_financial_health_score,
    compute_momentum_score,
    compute_price_changes,
    compute_valuation_score,
)

HISTORY_FIELDNAMES = [
    "date", "ticker", "shares", "price_local", "currency",
    "value_eur", "avg_cost_local", "gp_eur", "gp_pct",
    "day_change_pct", "week_change_pct", "month_change_pct",
    "valuation_score", "momentum_score", "financial_health_score",
]


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"


def history_csv_path() -> Path:
    return data_dir() / "portfolio_history.csv"


def build_snapshot_row(
    holding: dict,
    price_row: dict,
    fx_rate: float,
    price_history_rows: list[dict] | None = None,
    fundamentals_snapshot: dict | None = None,
    today_str: str | None = None,
) -> dict:
    result = compute_value_and_gp(
        shares=holding["shares"],
        price_local=float(price_row["close"]),
        avg_cost_local=holding["avg_cost_local"],
        fx_rate=fx_rate,
    )

    changes = compute_price_changes(price_history_rows or [])
    fund = fundamentals_snapshot or {}
    valuation_score = compute_valuation_score(
        price_local=float(price_row["close"]),
        fifty_two_week_low=fund.get("fifty_two_week_low"),
        fifty_two_week_high=fund.get("fifty_two_week_high"),
        pe_ratio=fund.get("pe_ratio"),
        forward_pe=fund.get("forward_pe"),
    )
    momentum_score = compute_momentum_score(changes["month_change_pct"])
    financial_health_score = compute_financial_health_score(
        debt_to_equity=fund.get("debt_to_equity"),
        profit_margin=fund.get("profit_margin"),
    )

    return {
        "date": today_str or date.today().isoformat(),
        "ticker": holding["ticker"],
        "shares": holding["shares"],
        "price_local": price_row["close"],
        "currency": holding["currency"],
        "value_eur": f"{result['value_eur']:.2f}",
        "avg_cost_local": holding["avg_cost_local"],
        "gp_eur": "" if result["gp_eur"] is None else f"{result['gp_eur']:.2f}",
        "gp_pct": "" if result["gp_pct"] is None else f"{result['gp_pct']:.2f}",
        "day_change_pct": _fmt(changes["day_change_pct"]),
        "week_change_pct": _fmt(changes["week_change_pct"]),
        "month_change_pct": _fmt(changes["month_change_pct"]),
        "valuation_score": _fmt(valuation_score),
        "momentum_score": _fmt(momentum_score),
        "financial_health_score": _fmt(financial_health_score),
    }


def currency_mismatch_warning(ticker: str, portfolio_currency: str, fundamentals_snapshot: dict | None) -> str | None:
    """Return a warning string if the fundamentals snapshot's live currency
    disagrees with portfolio.yaml's hand-typed currency, else None.

    Same bug class as the SAN incident: a hand-typed ticker/currency in
    portfolio.yaml can silently resolve to the wrong instrument on Yahoo
    Finance. This doesn't hard-fail the run — it just surfaces the mismatch.
    """
    if not fundamentals_snapshot:
        return None
    live_currency = fundamentals_snapshot.get("currency")
    if live_currency and live_currency != portfolio_currency:
        return (
            f"WARNING: {ticker} portfolio.yaml says currency={portfolio_currency} but "
            f"yfinance listing reports currency={live_currency} — this ticker may be "
            f"resolving to the wrong instrument, see the SAN incident"
        )
    return None


def safe_get_rate(ticker: str, currency: str, get_rate_fn=get_rate) -> float | None:
    """Fetch the FX rate for currency, returning None (and printing a warning)
    instead of raising if the fetch fails.

    Per the design spec: FX rate unavailable means EUR conversion is skipped
    for that holding this run rather than aborting the whole snapshot loop.
    """
    try:
        return get_rate_fn(currency)
    except Exception as e:
        print(
            f"{ticker}: FX rate fetch failed for {currency} ({e}) — EUR conversion "
            f"unavailable this run, skipping snapshot for this holding"
        )
        return None


def latest_history_by_ticker() -> dict[str, dict]:
    rows = load_csv_rows(history_csv_path())
    by_ticker: dict[str, list[dict]] = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], []).append(r)
    return {t: latest_by_date(rs) for t, rs in by_ticker.items()}


def previous_history_by_ticker() -> dict[str, dict]:
    """The second-most-recent history row per ticker — "last run", to compare
    today's scores against. Tickers with only one history row are omitted."""
    rows = load_csv_rows(history_csv_path())
    by_ticker: dict[str, list[dict]] = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], []).append(r)

    result = {}
    for ticker, ticker_rows in by_ticker.items():
        sorted_rows = sorted(ticker_rows, key=lambda r: r["date"])
        if len(sorted_rows) >= 2:
            result[ticker] = sorted_rows[-2]
    return result


def main():
    for holding in load_portfolio():
        ticker = holding["ticker"]
        price_rows = load_csv_rows(price_csv_path(ticker))
        if not price_rows:
            print(f"{ticker}: no price data yet, run fetch_prices first — skipping")
            continue
        price_row = latest_by_date(price_rows)

        fundamentals_snapshot = latest_fundamentals_snapshot(ticker)
        warning = currency_mismatch_warning(ticker, holding["currency"], fundamentals_snapshot)
        if warning:
            print(warning)

        fx_rate = safe_get_rate(ticker, holding["currency"])
        if fx_rate is None:
            continue

        row = build_snapshot_row(
            holding, price_row, fx_rate,
            price_history_rows=price_rows,
            fundamentals_snapshot=fundamentals_snapshot,
        )
        append_dedup_csv(history_csv_path(), [row], ["date", "ticker"], HISTORY_FIELDNAMES)
        gp_eur_display = row["gp_eur"] or "n/a"
        gp_pct_display = row["gp_pct"] or "n/a"
        print(f"{ticker}: value {row['value_eur']} EUR, G/P {gp_eur_display} EUR ({gp_pct_display}%)")


if __name__ == "__main__":
    main()
