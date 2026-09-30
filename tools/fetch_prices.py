import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

from tools.portfolio_lib import append_dedup_csv, data_dir, load_csv_rows

PRICE_FIELDNAMES = ["date", "open", "high", "low", "close", "volume"]


def price_csv_path(ticker: str) -> Path:
    return data_dir() / "prices" / f"{ticker}.csv"


def compute_start_date(ticker: str, default_lookback_days: int = 365, today: date | None = None) -> date:
    today = today or date.today()
    rows = load_csv_rows(price_csv_path(ticker))
    if not rows:
        return today - timedelta(days=default_lookback_days)
    last_date = max(datetime.strptime(r["date"], "%Y-%m-%d").date() for r in rows)
    return last_date + timedelta(days=1)


def fetch_price_history(ticker: str, start: date, end: date) -> list[dict]:
    if start > end:
        return []
    df = yf.download(
        ticker,
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        progress=False,
    )
    # Flatten MultiIndex columns if they exist
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(-1)

    rows = []
    for idx, row in df.iterrows():
        # Yahoo can return an unsettled session as volume-only with NaN OHLC
        if pd.isna(row["Close"]):
            continue
        rows.append(
            {
                "date": idx.strftime("%Y-%m-%d"),
                "open": f"{float(row['Open']):.4f}",
                "high": f"{float(row['High']):.4f}",
                "low": f"{float(row['Low']):.4f}",
                "close": f"{float(row['Close']):.4f}",
                "volume": str(int(row["Volume"])),
            }
        )
    return rows


def save_prices(ticker: str, rows: list[dict]) -> int:
    return append_dedup_csv(price_csv_path(ticker), rows, ["date"], PRICE_FIELDNAMES)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--start", help="YYYY-MM-DD override")
    args = parser.parse_args()

    start = date.fromisoformat(args.start) if args.start else compute_start_date(args.ticker)
    end = date.today()
    if start > end:
        print(f"{args.ticker}: already up to date")
        return

    rows = fetch_price_history(args.ticker, start, end)
    if not rows:
        print(f"{args.ticker}: fetched 0 days for range {start}..{end} — verify this is expected (e.g., weekend/holiday only) rather than a fetch issue")
        sys.exit(1)

    added = save_prices(args.ticker, rows)
    print(f"{args.ticker}: fetched {len(rows)} days, {added} new")


if __name__ == "__main__":
    main()
