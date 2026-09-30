import argparse
import sys
from datetime import date
from pathlib import Path

import yaml
import yfinance as yf

from tools.portfolio_lib import data_dir, latest_by_date, load_yaml_list

# Units: dividend_yield is a percent (e.g. 2.8 means 2.8%); profit_margin is a
# fraction (e.g. 0.11 means 11%); market_cap is in the instrument's own
# trading currency, not EUR.
FUNDAMENTALS_FIELDS = {
    "pe_ratio": "trailingPE",
    "forward_pe": "forwardPE",
    "debt_to_equity": "debtToEquity",
    "dividend_yield": "dividendYield",
    "market_cap": "marketCap",
    "profit_margin": "profitMargins",
    "fifty_two_week_low": "fiftyTwoWeekLow",
    "fifty_two_week_high": "fiftyTwoWeekHigh",
    "currency": "currency",
    "long_name": "longName",
    "exchange": "exchange",
    # Used for the allocation breakdown; ETFs return quote_type "ETF" and no sector/country.
    "quote_type": "quoteType",
    "sector": "sector",
    "industry": "industry",
    "country": "country",
    # Dividend safety and quality inputs for tools/analyst.py. Units: payout_ratio,
    # revenue_growth, earnings_growth, operating_margins and current_ratio are
    # fractions/ratios; dividend_rate is currency per share per year;
    # five_year_avg_dividend_yield is a percent, like dividend_yield.
    "payout_ratio": "payoutRatio",
    "dividend_rate": "dividendRate",
    "five_year_avg_dividend_yield": "fiveYearAvgDividendYield",
    "free_cashflow": "freeCashflow",
    "shares_outstanding": "sharesOutstanding",
    "revenue_growth": "revenueGrowth",
    "earnings_growth": "earningsGrowth",
    "operating_margins": "operatingMargins",
    "current_ratio": "currentRatio",
    "price_to_book": "priceToBook",
    "target_mean_price": "targetMeanPrice",
    "recommendation_key": "recommendationKey",
    "beta": "beta",
}


def fundamentals_yaml_path(ticker: str) -> Path:
    return data_dir() / "fundamentals" / f"{ticker}.yaml"


def extract_fundamentals(info: dict, today_str: str | None = None) -> dict:
    snapshot = {"date": today_str or date.today().isoformat()}
    for local_key, info_key in FUNDAMENTALS_FIELDS.items():
        if info_key in info:
            snapshot[local_key] = info[info_key]
    return snapshot


def fetch_info_live(ticker: str) -> dict:
    return yf.Ticker(ticker).info


def save_fundamentals(ticker: str, snapshot: dict) -> None:
    """Append a fundamentals snapshot, replacing any existing entry for the same date.

    Unlike append_yaml_list (used as-is by callers like append_analysis that
    intentionally want every entry kept), fundamentals snapshots are a
    point-in-time read of "today's" data — running fetch_fundamentals twice
    in one day should produce one up-to-date snapshot for that date, not two.
    """
    path = fundamentals_yaml_path(ticker)
    existing = [e for e in load_yaml_list(path, "snapshots") if e.get("date") != snapshot.get("date")]
    existing.append(snapshot)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump({"snapshots": existing}, f, sort_keys=False, allow_unicode=True)


def latest_fundamentals_snapshot(ticker: str) -> dict | None:
    return latest_by_date(load_yaml_list(fundamentals_yaml_path(ticker), "snapshots"))


def summary_line(ticker: str, snapshot: dict) -> str:
    """Format a summary line for a fundamentals snapshot.

    Uses .get() for fields that may be absent due to instrument type limitations
    (e.g., ETFs commonly lack debtToEquity in yfinance data).
    """
    pe = snapshot.get("pe_ratio")
    debt = snapshot.get("debt_to_equity")
    div_yield = snapshot.get("dividend_yield")
    return f"{ticker}: P/E {pe}, Debt/Equity {debt}, Div Yield {div_yield}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    args = parser.parse_args()

    info = fetch_info_live(args.ticker)

    # Check if fetch returned valid data (symbol is present and not None)
    if not info.get("symbol"):
        print(f"{args.ticker}: fetch failed — yfinance returned no usable data, not saving a snapshot")
        sys.exit(1)

    snapshot = extract_fundamentals(info)
    save_fundamentals(args.ticker, snapshot)
    print(summary_line(args.ticker, snapshot))


if __name__ == "__main__":
    main()
