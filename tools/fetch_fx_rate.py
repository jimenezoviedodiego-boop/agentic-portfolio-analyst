import argparse
from pathlib import Path
from datetime import date

import yaml
import yfinance as yf

from tools.portfolio_lib import data_dir


def cache_path(currency: str) -> Path:
    return data_dir() / "fx_cache" / f"{currency}EUR.yaml"


def _read_cache(currency: str) -> dict | None:
    path = cache_path(currency)
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write_cache(currency: str, today_str: str, rate: float) -> None:
    path = cache_path(currency)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"date": today_str, "rate": rate}), encoding="utf-8")


def fetch_rate_live(currency: str) -> float:
    ticker = f"{currency}EUR=X"
    data = yf.Ticker(ticker).history(period="1d")
    return float(data["Close"].iloc[-1])


def get_rate(currency: str, today_str: str | None = None, fetch_fn=None) -> float:
    if currency == "EUR":
        return 1.0

    fetch_fn = fetch_fn or fetch_rate_live
    today_str = today_str or date.today().isoformat()

    cached = _read_cache(currency)
    if cached and cached.get("date") == today_str:
        return cached["rate"]

    rate = fetch_fn(currency)
    _write_cache(currency, today_str, rate)
    return rate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--currency", required=True)
    args = parser.parse_args()
    rate = get_rate(args.currency)
    print(f"1 {args.currency} = {rate} EUR")


if __name__ == "__main__":
    main()
