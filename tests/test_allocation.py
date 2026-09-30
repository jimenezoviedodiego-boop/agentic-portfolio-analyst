import pytest

from tools.allocation import (
    ETF_COUNTRY_LABEL,
    ETF_SECTOR_LABEL,
    POSITION_LIMIT_PCT,
    SECTOR_LIMIT_PCT,
    UNKNOWN_LABEL,
    compute_allocation,
    holding_country,
    holding_sector,
)


def test_holding_sector_uses_fundamentals_sector():
    assert holding_sector({"quote_type": "EQUITY", "sector": "Healthcare"}) == "Healthcare"


def test_holding_sector_labels_etfs_and_missing_data():
    assert holding_sector({"quote_type": "ETF", "sector": None}) == ETF_SECTOR_LABEL
    assert holding_sector({"quote_type": "EQUITY", "sector": None}) == UNKNOWN_LABEL
    assert holding_sector({}) == UNKNOWN_LABEL


def test_holding_country_labels_etfs_and_missing_data():
    assert holding_country({"quote_type": "EQUITY", "country": "France"}) == "France"
    assert holding_country({"quote_type": "ETF", "country": None}) == ETF_COUNTRY_LABEL
    assert holding_country({}) == UNKNOWN_LABEL


def _fixture():
    holdings = [
        {"ticker": "AAA", "company": "Alpha Health"},
        {"ticker": "BBB", "company": "Beta Health"},
        {"ticker": "CCC", "company": "Gamma Foods"},
        {"ticker": "ETF", "company": "Index Fund"},
    ]
    latest_history = {
        "AAA": {"value_eur": "600.00", "gp_eur": "400.00"},   # invested 200
        "BBB": {"value_eur": "100.00", "gp_eur": "-50.00"},   # invested 150
        "CCC": {"value_eur": "200.00", "gp_eur": ""},         # invested unknown (spin-off)
        "ETF": {"value_eur": "100.00", "gp_eur": "0.00"},     # invested 100
    }
    latest_fundamentals = {
        "AAA": {"quote_type": "EQUITY", "sector": "Healthcare", "industry": "Drugs", "country": "United States"},
        "BBB": {"quote_type": "EQUITY", "sector": "Healthcare", "industry": "Devices", "country": "France"},
        "CCC": {"quote_type": "EQUITY", "sector": "Consumer Defensive", "industry": "Foods", "country": "United States"},
        "ETF": {"quote_type": "ETF"},
    }
    return holdings, latest_history, latest_fundamentals


def test_compute_allocation_totals_and_position_weights_sorted_by_value():
    alloc = compute_allocation(*_fixture())

    assert alloc["total_eur"] == pytest.approx(1000.0)
    # Only positions with a known cost basis count toward "invested".
    assert alloc["total_invested_eur"] == pytest.approx(450.0)

    tickers = [p["ticker"] for p in alloc["positions"]]
    assert tickers == ["AAA", "CCC", "BBB", "ETF"]  # value desc, ties broken by ticker
    aaa = alloc["positions"][0]
    assert aaa["weight_pct"] == pytest.approx(60.0)
    assert aaa["invested_eur"] == pytest.approx(200.0)
    assert aaa["sector"] == "Healthcare"
    ccc = next(p for p in alloc["positions"] if p["ticker"] == "CCC")
    assert ccc["invested_eur"] is None


def test_compute_allocation_groups_by_sector_and_country():
    alloc = compute_allocation(*_fixture())

    sectors = {s["name"]: s for s in alloc["sectors"]}
    assert alloc["sectors"][0]["name"] == "Healthcare"  # largest first
    assert sectors["Healthcare"]["value_eur"] == pytest.approx(700.0)
    assert sectors["Healthcare"]["weight_pct"] == pytest.approx(70.0)
    assert sectors["Healthcare"]["tickers"] == ["AAA", "BBB"]  # by value within group
    assert sectors[ETF_SECTOR_LABEL]["weight_pct"] == pytest.approx(10.0)

    countries = {c["name"]: c for c in alloc["countries"]}
    assert countries["United States"]["weight_pct"] == pytest.approx(80.0)
    assert countries["France"]["weight_pct"] == pytest.approx(10.0)
    assert countries[ETF_COUNTRY_LABEL]["weight_pct"] == pytest.approx(10.0)


def test_compute_allocation_flags_concentration_above_limits():
    alloc = compute_allocation(*_fixture())
    flags = alloc["flags"]

    # AAA: 60% > POSITION_LIMIT_PCT, and it grew into that weight (200 in, 600 now).
    aaa_flag = next(f for f in flags if "(AAA)" in f)
    assert f"{POSITION_LIMIT_PCT:.0f}%" in aaa_flag
    assert "200" in aaa_flag and "600" in aaa_flag
    # Healthcare: 70% > SECTOR_LIMIT_PCT.
    assert any("Healthcare" in f and f"{SECTOR_LIMIT_PCT:.0f}%" in f for f in flags)
    # The ETF is diversified by construction - never flagged as a concentrated position.
    assert not any("(ETF)" in f for f in flags)


def test_compute_allocation_no_flags_when_spread_out():
    holdings = [{"ticker": f"T{i}", "company": f"Co {i}"} for i in range(10)]
    history = {f"T{i}": {"value_eur": "100", "gp_eur": "0"} for i in range(10)}
    sectors = ["A", "B", "C", "D", "E"]
    fundamentals = {f"T{i}": {"quote_type": "EQUITY", "sector": sectors[i % 5]} for i in range(10)}

    alloc = compute_allocation(holdings, history, fundamentals)
    assert alloc["flags"] == []


def test_compute_allocation_skips_holdings_without_a_value():
    holdings = [{"ticker": "AAA", "company": "A"}, {"ticker": "ZZZ", "company": "Z"}]
    history = {"AAA": {"value_eur": "100", "gp_eur": "0"}}
    alloc = compute_allocation(holdings, history, {})
    assert [p["ticker"] for p in alloc["positions"]] == ["AAA"]
    assert alloc["total_eur"] == pytest.approx(100.0)
