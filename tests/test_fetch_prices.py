from datetime import date

from tools.fetch_prices import compute_start_date, price_csv_path, save_prices
from tools.portfolio_lib import load_csv_rows


def test_compute_start_date_defaults_to_lookback_when_no_history(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path))
    start = compute_start_date("HON", default_lookback_days=30, today=date(2026, 9, 16))
    assert start == date(2026, 8, 17)


def test_compute_start_date_resumes_after_last_cached_date(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path))
    save_prices("HON", [
        {"date": "2026-09-10", "open": "1", "high": "1", "low": "1", "close": "1", "volume": "1"},
        {"date": "2026-09-12", "open": "1", "high": "1", "low": "1", "close": "1", "volume": "1"},
    ])
    start = compute_start_date("HON", today=date(2026, 9, 16))
    assert start == date(2026, 9, 13)


def test_save_prices_dedups_by_date(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path))
    row = {"date": "2026-09-10", "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "1000"}
    added1 = save_prices("HON", [row])
    added2 = save_prices("HON", [row])
    assert added1 == 1
    assert added2 == 0
    assert len(load_csv_rows(price_csv_path("HON"))) == 1


def test_compute_start_date_default_lookback_is_one_year(tmp_path, monkeypatch):
    # Technical indicators (Konkorde needs ~105 bars) require a year of
    # history, so a brand-new holding fetches 365 days by default.
    monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path))
    start = compute_start_date("NEWCO", today=date(2026, 9, 18))
    assert start == date(2025, 9, 18)


def test_fetch_price_history_skips_rows_without_a_close(monkeypatch):
    # Yahoo sometimes returns the latest European session as a volume-only
    # row with NaN OHLC; storing it made record_snapshot value the holding
    # at NaN. Skipping it lets the next fetch resume from that date.
    import pandas as pd
    from tools import fetch_prices

    nan = float("nan")
    df = pd.DataFrame(
        {"Open": [60.5, nan], "High": [61.2, nan], "Low": [60.4, nan],
         "Close": [60.9, nan], "Volume": [977416, 1034479]},
        index=pd.to_datetime(["2026-09-22", "2026-09-23"]),
    )
    monkeypatch.setattr(fetch_prices.yf, "download", lambda *a, **k: df)
    rows = fetch_prices.fetch_price_history("SAN.PA", date(2026, 9, 22), date(2026, 9, 24))
    assert [r["date"] for r in rows] == ["2026-09-22"]
