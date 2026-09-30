import csv

import yaml

from tools.portfolio_lib import (
    append_dedup_csv,
    append_dedup_jsonl,
    append_yaml_list,
    load_csv_rows,
    load_jsonl_rows,
    load_portfolio,
    load_yaml_list,
    latest_by_date,
)


def test_append_dedup_csv_adds_new_and_updates_existing(tmp_path):
    path = tmp_path / "prices.csv"
    fieldnames = ["date", "close"]

    added1 = append_dedup_csv(path, [{"date": "2026-09-01", "close": "10.0"}], ["date"], fieldnames)
    assert added1 == 1

    added2 = append_dedup_csv(
        path,
        [{"date": "2026-09-01", "close": "10.5"}, {"date": "2026-09-02", "close": "11.0"}],
        ["date"],
        fieldnames,
    )
    assert added2 == 1  # only 09-02 is genuinely new; 09-01 is overwritten

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert rows == [
        {"date": "2026-09-01", "close": "10.5"},
        {"date": "2026-09-02", "close": "11.0"},
    ]


def test_append_dedup_jsonl_skips_existing_by_key(tmp_path):
    path = tmp_path / "news.jsonl"

    added1 = append_dedup_jsonl(path, [{"url": "https://a", "title": "A"}], "url")
    assert added1 == 1

    added2 = append_dedup_jsonl(
        path,
        [{"url": "https://a", "title": "A (dup)"}, {"url": "https://b", "title": "B"}],
        "url",
    )
    assert added2 == 1

    rows = load_jsonl_rows(path)
    assert [r["url"] for r in rows] == ["https://a", "https://b"]
    assert rows[0]["title"] == "A"  # first write wins, dup ignored


def test_append_yaml_list_creates_and_appends(tmp_path):
    path = tmp_path / "analysis.yaml"

    append_yaml_list(path, {"date": "2026-09-01", "note": "first"}, "entries")
    append_yaml_list(path, {"date": "2026-09-02", "note": "second"}, "entries")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert [e["note"] for e in data["entries"]] == ["first", "second"]

    loaded = load_yaml_list(path, "entries")
    assert len(loaded) == 2


def test_load_csv_rows_returns_empty_list_when_missing(tmp_path):
    assert load_csv_rows(tmp_path / "missing.csv") == []


def test_load_portfolio_combines_holdings_and_etfs_with_is_etf_flag(tmp_path):
    path = tmp_path / "portfolio.yaml"
    path.write_text(
        """
holdings:
  - ticker: HON
    company: Honeywell International
    isin: US4385161066
    exchange: NYSE
    currency: USD
    shares: 10
    avg_cost_local: 120.50
    notes: ""
etfs:
  - ticker: VWRL
    company: Vanguard FTSE All-World UCITS ETF USD Dis
    isin: IE00B3RBWM25
    exchange: EAM
    currency: EUR
    shares: 20
    avg_cost_local: 80.25
    notes: ""
""",
        encoding="utf-8",
    )

    holdings = load_portfolio(path)
    by_ticker = {h["ticker"]: h for h in holdings}

    assert by_ticker["HON"]["is_etf"] is False
    assert by_ticker["VWRL"]["is_etf"] is True
    assert by_ticker["HON"]["shares"] == 10


def test_latest_by_date_picks_max_date():
    entries = [{"date": "2026-09-01"}, {"date": "2026-09-16"}, {"date": "2026-09-08"}]
    assert latest_by_date(entries)["date"] == "2026-09-16"
    assert latest_by_date([]) is None
