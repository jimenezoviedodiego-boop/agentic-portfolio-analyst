from tools.fetch_fundamentals import (
    extract_fundamentals,
    fundamentals_yaml_path,
    latest_fundamentals_snapshot,
    save_fundamentals,
    summary_line,
)
from tools.portfolio_lib import load_yaml_list


def test_extract_fundamentals_maps_known_fields_and_handles_missing():
    info = {
        "trailingPE": 22.4,
        "forwardPE": 20.1,
        "debtToEquity": 145.3,
        "dividendYield": 0.028,
        "marketCap": 68_000_000_000,
        "profitMargins": 0.11,
        # fiftyTwoWeekLow/High intentionally absent, mimicking an ETF
    }
    snapshot = extract_fundamentals(info, today_str="2026-09-16")
    assert snapshot["date"] == "2026-09-16"
    assert snapshot["pe_ratio"] == 22.4
    assert snapshot["debt_to_equity"] == 145.3
    assert "fifty_two_week_low" not in snapshot
    assert "fifty_two_week_high" not in snapshot


def test_extract_fundamentals_captures_currency_long_name_and_exchange():
    info = {
        "trailingPE": 22.4,
        "currency": "USD",
        "longName": "Honeywell International",
        "exchange": "NYQ",
    }
    snapshot = extract_fundamentals(info, today_str="2026-09-16")
    assert snapshot["currency"] == "USD"
    assert snapshot["long_name"] == "Honeywell International"
    assert snapshot["exchange"] == "NYQ"


def test_save_and_load_latest_fundamentals_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path))
    save_fundamentals("HON", extract_fundamentals({"trailingPE": 20.0}, today_str="2026-09-01"))
    save_fundamentals("HON", extract_fundamentals({"trailingPE": 22.0}, today_str="2026-09-16"))

    latest = latest_fundamentals_snapshot("HON")
    assert latest["date"] == "2026-09-16"
    assert latest["pe_ratio"] == 22.0


def test_save_fundamentals_replaces_same_date_snapshot_instead_of_duplicating(tmp_path, monkeypatch):
    # Regression test: running fetch_fundamentals twice in one day used to
    # append two same-date snapshots, and latest_by_date's max() with a tie
    # returns the FIRST (older, stale) one — so the Sheet showed stale P/E.
    monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path))
    save_fundamentals("ABBV", extract_fundamentals({"trailingPE": 23.878864}, today_str="2026-09-16"))
    save_fundamentals("ABBV", extract_fundamentals({"trailingPE": 23.720188}, today_str="2026-09-16"))

    snapshots = load_yaml_list(fundamentals_yaml_path("ABBV"), "snapshots")
    assert len(snapshots) == 1
    assert snapshots[0]["pe_ratio"] == 23.720188

    latest = latest_fundamentals_snapshot("ABBV")
    assert latest["pe_ratio"] == 23.720188


def test_extract_fundamentals_captures_sector_industry_country_and_quote_type():
    info = {
        "quoteType": "EQUITY",
        "sector": "Industrials",
        "industry": "Conglomerates",
        "country": "United States",
    }
    snapshot = extract_fundamentals(info, today_str="2026-09-18")
    assert snapshot["quote_type"] == "EQUITY"
    assert snapshot["sector"] == "Industrials"
    assert snapshot["industry"] == "Conglomerates"
    assert snapshot["country"] == "United States"


def test_extract_fundamentals_stores_dividend_and_quality_fields():
    info = {
        "payoutRatio": 0.7533,
        "dividendRate": 5.92,
        "fiveYearAvgDividendYield": 3.03,
        "freeCashflow": 7831875072,
        "sharesOutstanding": 1371700000,
        "revenueGrowth": 0.064,
        "earningsGrowth": 1.37,
        "operatingMargins": 0.16836,
        "currentRatio": 0.934,
        "priceToBook": 8.020647,
        "targetMeanPrice": 155.0,
        "recommendationKey": "hold",
        "beta": 0.361,
    }

    snapshot = extract_fundamentals(info, today_str="2026-09-21")

    assert snapshot["payout_ratio"] == 0.7533
    assert snapshot["dividend_rate"] == 5.92
    assert snapshot["five_year_avg_dividend_yield"] == 3.03
    assert snapshot["free_cashflow"] == 7831875072
    assert snapshot["shares_outstanding"] == 1371700000
    assert snapshot["revenue_growth"] == 0.064
    assert snapshot["earnings_growth"] == 1.37
    assert snapshot["operating_margins"] == 0.16836
    assert snapshot["current_ratio"] == 0.934
    assert snapshot["price_to_book"] == 8.020647
    assert snapshot["target_mean_price"] == 155.0
    assert snapshot["recommendation_key"] == "hold"
    assert snapshot["beta"] == 0.361


def test_extract_fundamentals_omits_missing_new_fields():
    snapshot = extract_fundamentals({"trailingPE": 20.0}, today_str="2026-09-21")

    assert snapshot["pe_ratio"] == 20.0
    for absent in ("payout_ratio", "free_cashflow", "target_mean_price"):
        assert absent not in snapshot


def test_summary_line_handles_missing_fields():
    # Regression test: ETFs (e.g. VWRL.AS) commonly lack debtToEquity, so
    # summary_line must not raise KeyError when pe_ratio/debt_to_equity/
    # dividend_yield are absent from snapshot. Uses .get() to provide None.
    snapshot = extract_fundamentals({}, today_str="2026-09-21")

    # Should not raise KeyError; should produce a valid string
    result = summary_line("VWRL.AS", snapshot)
    assert isinstance(result, str)
    assert "VWRL.AS" in result
    assert "None" in result  # All three fields are None
