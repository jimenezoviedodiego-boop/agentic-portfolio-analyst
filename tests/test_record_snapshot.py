import pytest

from tools.record_snapshot import (
    build_snapshot_row,
    currency_mismatch_warning,
    latest_history_by_ticker,
    history_csv_path,
    previous_history_by_ticker,
    safe_get_rate,
)
from tools.portfolio_lib import append_dedup_csv


def test_build_snapshot_row_computes_value_and_gp():
    holding = {"ticker": "TESTCO", "shares": 20, "avg_cost_local": 50.0, "currency": "EUR"}
    price_row = {"date": "2026-09-16", "close": "60.98"}

    row = build_snapshot_row(holding, price_row, fx_rate=1.0, today_str="2026-09-16")

    assert row["ticker"] == "TESTCO"
    assert row["date"] == "2026-09-16"
    assert float(row["value_eur"]) > 0
    assert row["gp_pct"] != ""


def test_build_snapshot_row_zero_avg_cost_leaves_gp_and_gp_pct_blank():
    holding = {"ticker": "KD", "shares": 3, "avg_cost_local": 0.0, "currency": "USD"}
    price_row = {"date": "2026-09-16", "close": "90.925"}

    row = build_snapshot_row(holding, price_row, fx_rate=0.9, today_str="2026-09-16")

    assert row["gp_pct"] == ""
    assert row["gp_eur"] == ""  # unknown cost basis must not leak a phantom gain into the CSV


def test_build_snapshot_row_includes_price_changes_and_scores():
    holding = {"ticker": "TESTCO", "shares": 10, "avg_cost_local": 50.0, "currency": "USD"}
    price_history_rows = [
        {"date": "2026-08-17", "close": "100.0"},
        {"date": "2026-09-09", "close": "110.0"},
        {"date": "2026-09-15", "close": "120.0"},
        {"date": "2026-09-16", "close": "132.0"},
    ]
    price_row = price_history_rows[-1]
    fundamentals_snapshot = {
        "fifty_two_week_low": 90.0,
        "fifty_two_week_high": 150.0,
        "pe_ratio": 20.0,
        "forward_pe": 15.0,
        "debt_to_equity": 50.0,
        "profit_margin": 0.15,
    }

    row = build_snapshot_row(
        holding, price_row, fx_rate=1.0,
        price_history_rows=price_history_rows,
        fundamentals_snapshot=fundamentals_snapshot,
        today_str="2026-09-16",
    )

    assert float(row["day_change_pct"]) == pytest.approx(10.0)
    assert float(row["week_change_pct"]) == pytest.approx(20.0)
    assert float(row["month_change_pct"]) == pytest.approx(32.0)
    assert 0.0 <= float(row["valuation_score"]) <= 100.0
    assert 0.0 <= float(row["momentum_score"]) <= 100.0
    assert 0.0 <= float(row["financial_health_score"]) <= 100.0


def test_build_snapshot_row_without_history_or_fundamentals_leaves_new_fields_blank():
    holding = {"ticker": "TESTCO", "shares": 10, "avg_cost_local": 50.0, "currency": "USD"}
    price_row = {"date": "2026-09-16", "close": "60.0"}

    row = build_snapshot_row(holding, price_row, fx_rate=1.0, today_str="2026-09-16")

    assert row["day_change_pct"] == ""
    assert row["week_change_pct"] == ""
    assert row["month_change_pct"] == ""
    assert row["valuation_score"] == ""
    assert row["momentum_score"] == ""
    assert row["financial_health_score"] == ""


def test_previous_history_by_ticker_returns_second_latest(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path))
    fieldnames = ["date", "ticker", "value_eur"]
    append_dedup_csv(
        history_csv_path(),
        [
            {"date": "2026-09-01", "ticker": "HON", "value_eur": "1800"},
            {"date": "2026-09-10", "ticker": "HON", "value_eur": "1820"},
            {"date": "2026-09-16", "ticker": "HON", "value_eur": "1500.00"},
        ],
        ["date", "ticker"],
        fieldnames,
    )

    previous = previous_history_by_ticker()
    assert previous["HON"]["date"] == "2026-09-10"


def test_previous_history_by_ticker_omits_single_entry_tickers(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path))
    fieldnames = ["date", "ticker", "value_eur"]
    append_dedup_csv(
        history_csv_path(),
        [{"date": "2026-09-16", "ticker": "ONLYONE", "value_eur": "100"}],
        ["date", "ticker"],
        fieldnames,
    )

    assert previous_history_by_ticker() == {}


def test_currency_mismatch_warning_flags_disagreement():
    warning = currency_mismatch_warning("TESTCO", "EUR", {"currency": "USD"})
    assert warning is not None
    assert "TESTCO" in warning
    assert "currency=EUR" in warning
    assert "currency=USD" in warning


def test_currency_mismatch_warning_silent_when_matching():
    assert currency_mismatch_warning("HON", "USD", {"currency": "USD"}) is None


def test_currency_mismatch_warning_silent_when_no_fundamentals_yet():
    assert currency_mismatch_warning("HON", "USD", None) is None


def test_safe_get_rate_returns_none_and_warns_on_failure(capsys):
    def failing_get_rate(currency):
        raise IndexError("single positional indexer is out-of-bounds")

    result = safe_get_rate("TESTCO", "USD", get_rate_fn=failing_get_rate)

    assert result is None
    captured = capsys.readouterr()
    assert "TESTCO" in captured.out
    assert "USD" in captured.out


def test_safe_get_rate_returns_rate_on_success():
    result = safe_get_rate("TESTCO", "USD", get_rate_fn=lambda currency: 0.92)
    assert result == 0.92


def test_latest_history_by_ticker_groups_and_picks_latest(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path))
    fieldnames = [
        "date", "ticker", "shares", "price_local", "currency",
        "value_eur", "avg_cost_local", "gp_eur", "gp_pct",
    ]
    append_dedup_csv(
        history_csv_path(),
        [
            {"date": "2026-09-01", "ticker": "HON", "shares": "10", "price_local": "160", "currency": "USD", "value_eur": "1800", "avg_cost_local": "120", "gp_eur": "300", "gp_pct": "20"},
            {"date": "2026-09-16", "ticker": "HON", "shares": "10", "price_local": "163.9", "currency": "USD", "value_eur": "1500.00", "avg_cost_local": "120", "gp_eur": "350", "gp_pct": "23"},
        ],
        ["date", "ticker"],
        fieldnames,
    )

    latest = latest_history_by_ticker()
    assert latest["HON"]["date"] == "2026-09-16"
