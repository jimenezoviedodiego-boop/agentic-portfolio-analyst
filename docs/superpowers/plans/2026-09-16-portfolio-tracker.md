# Portfolio Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the WAT subsystem that tracks the owner's existing long-term
stock holdings — price history, news, fundamentals, cost-basis/gain-loss,
and an agent-written "why did it move / what's the status" narrative —
and syncs it to a Google Sheet (data) and Google Doc (summary report).

**Architecture:** Deterministic Python tools in `tools/` fetch and
store data under `data/` (gitignored: prices CSV, news JSONL,
fundamentals YAML, computed value/G-P history CSV, agent-written
analysis YAML). Two workflow SOPs in `workflows/` document how the agent
orchestrates those tools. Two sync tools push the assembled data to
Google Sheets and Google Docs.

**Tech Stack:** Python 3, `yfinance` (prices, FX, fundamentals),
`feedparser` (Google News RSS), `pyyaml`, `gspread` + `google-auth` +
`google-auth-oauthlib` + `google-api-python-client` (Google Sheets/Docs),
`pytest`.

**Spec:** `docs/superpowers/specs/2026-09-16-portfolio-tracker-design.md`

## Global Constraints

- No API keys required for price/news/fundamentals/FX data — free
  sources only (`yfinance`, Google News RSS) for v1.
- All personal financial data (holdings, prices, computed value/G-P)
  lives under `data/`, which is gitignored. Never write holding amounts
  or values into a git-tracked file.
- Manual trigger only — no scheduling/cron automation in this iteration.
- On any fetch failure, tools must exit non-zero with a clear error —
  never fabricate or silently skip data.
- `avg_cost_local` is assumed to be in the instrument's own trading
  currency. This must be validated against the owner's real G/P figures
  (Task 8) before being trusted, and the assumption corrected if wrong.
- Tools are invoked as modules from the repo root: `python -m
  tools.<name> [args]`. Tests are run as `pytest` from the repo root.

---

### Task 1: Project setup & shared I/O library

**Files:**
- Create: `requirements.txt`
- Create: `conftest.py` (empty — establishes repo root on `sys.path` for pytest)
- Create: `tools/__init__.py` (empty)
- Create: `tools/portfolio_lib.py`
- Test: `tests/test_portfolio_lib.py`

**Interfaces:**
- Produces (used by every later task):
  - `repo_root() -> Path`
  - `data_dir() -> Path` (honors `PORTFOLIO_DATA_DIR` env override for tests)
  - `load_portfolio(path: Path | None = None) -> list[dict]` — each dict has `ticker, company, isin, exchange, currency, shares, avg_cost_local, notes, is_etf`
  - `append_dedup_csv(path: Path, new_rows: list[dict], key_fields: list[str], fieldnames: list[str]) -> int`
  - `append_dedup_jsonl(path: Path, new_rows: list[dict], key_field: str) -> int`
  - `append_yaml_list(path: Path, new_entry: dict, list_key: str) -> None`
  - `load_yaml_list(path: Path, list_key: str) -> list[dict]`
  - `load_csv_rows(path: Path) -> list[dict]`
  - `load_jsonl_rows(path: Path) -> list[dict]`
  - `latest_by_date(entries: list[dict], date_field: str = "date") -> dict | None`

- [ ] **Step 1: Create `requirements.txt`**

```
pyyaml
yfinance
feedparser
gspread
google-auth
google-auth-oauthlib
google-api-python-client
pytest
```

- [ ] **Step 2: Create empty `conftest.py` at repo root and `tools/__init__.py`**

Both files are empty. `conftest.py` at the repo root makes pytest add the
repo root to `sys.path`, so test files can `from tools.portfolio_lib
import ...`.

- [ ] **Step 3: Install dependencies**

Run: `pip install -r requirements.txt`

- [ ] **Step 4: Write the failing tests**

```python
# tests/test_portfolio_lib.py
import csv
import json
from pathlib import Path

import pytest
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
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `pytest tests/test_portfolio_lib.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.portfolio_lib'`

- [ ] **Step 6: Implement `tools/portfolio_lib.py`**

```python
import csv
import json
import os
from pathlib import Path

import yaml


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    override = os.environ.get("PORTFOLIO_DATA_DIR")
    if override:
        return Path(override)
    return repo_root() / "data"


def load_portfolio(path: Path | None = None) -> list[dict]:
    path = path or (data_dir() / "portfolio.yaml")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    holdings = []
    for h in data.get("holdings", []):
        h = dict(h)
        h["is_etf"] = False
        holdings.append(h)
    for h in data.get("etfs", []):
        h = dict(h)
        h["is_etf"] = True
        holdings.append(h)
    return holdings


def append_dedup_csv(path: Path, new_rows: list[dict], key_fields: list[str], fieldnames: list[str]) -> int:
    existing: dict[tuple, dict] = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = tuple(row[k] for k in key_fields)
                existing[key] = row

    added = 0
    for row in new_rows:
        row = {k: str(row.get(k, "")) for k in fieldnames}
        key = tuple(row[k] for k in key_fields)
        if key not in existing:
            added += 1
        existing[key] = row

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for key in sorted(existing.keys()):
            writer.writerow(existing[key])

    return added


def append_dedup_jsonl(path: Path, new_rows: list[dict], key_field: str) -> int:
    existing_keys = set()
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    existing_keys.add(json.loads(line)[key_field])

    added = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in new_rows:
            if row[key_field] in existing_keys:
                continue
            f.write(json.dumps(row) + "\n")
            existing_keys.add(row[key_field])
            added += 1
    return added


def append_yaml_list(path: Path, new_entry: dict, list_key: str) -> None:
    data = {list_key: []}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if loaded:
            data = loaded

    data.setdefault(list_key, []).append(new_entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def load_yaml_list(path: Path, list_key: str) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return (data or {}).get(list_key, [])


def load_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_jsonl_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def latest_by_date(entries: list[dict], date_field: str = "date") -> dict | None:
    if not entries:
        return None
    return max(entries, key=lambda e: e[date_field])
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_portfolio_lib.py -v`
Expected: PASS (6 tests)

- [ ] **Step 8: Commit**

```bash
git add requirements.txt conftest.py tools/__init__.py tools/portfolio_lib.py tests/test_portfolio_lib.py
git commit -m "feat: add shared portfolio I/O library"
```

---

### Task 2: Portfolio math (value / gain-loss)

**Files:**
- Create: `tools/portfolio_math.py`
- Test: `tests/test_portfolio_math.py`

**Interfaces:**
- Produces (used by Task 8, Task 10, Task 11):
  - `compute_value_and_gp(shares: float, price_local: float, avg_cost_local: float, fx_rate: float) -> dict` — returns `{"value_eur": float, "gp_eur": float, "gp_pct": float | None}`. `gp_pct` is `None` when `avg_cost_local == 0` (cost basis unknown — see `KD` in `data/portfolio.yaml`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_portfolio_math.py
import pytest

from tools.portfolio_math import compute_value_and_gp


def test_same_currency_holding_uses_fx_rate_of_one():
    # EUR-denominated example: 20 shares, price 60.98, avg cost 50.00
    result = compute_value_and_gp(shares=20, price_local=60.98, avg_cost_local=50.0, fx_rate=1.0)
    assert result["value_eur"] == pytest.approx(1219.60, abs=0.01)
    assert result["gp_eur"] > 0
    assert result["gp_pct"] == pytest.approx(21.96, abs=0.1)


def test_cross_currency_holding_applies_fx_rate():
    result = compute_value_and_gp(shares=10, price_local=100.0, avg_cost_local=80.0, fx_rate=0.9)
    assert result["value_eur"] == pytest.approx(900.0)
    assert result["gp_eur"] == pytest.approx(900.0 - 720.0)
    assert result["gp_pct"] == pytest.approx(25.0)


def test_zero_avg_cost_returns_none_gp_pct():
    # KD: broker-reported breakeven price of 0.00 (spinoff share, no tracked cost basis)
    result = compute_value_and_gp(shares=3, price_local=90.925, avg_cost_local=0.0, fx_rate=0.9)
    assert result["gp_pct"] is None
    assert result["value_eur"] == pytest.approx(3 * 90.925 * 0.9)
    assert result["gp_eur"] == result["value_eur"]  # full value counted as gain vs zero cost
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_portfolio_math.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.portfolio_math'`

- [ ] **Step 3: Implement `tools/portfolio_math.py`**

```python
def compute_value_and_gp(shares: float, price_local: float, avg_cost_local: float, fx_rate: float) -> dict:
    value_eur = shares * price_local * fx_rate
    cost_eur = shares * avg_cost_local * fx_rate
    gp_eur = value_eur - cost_eur
    gp_pct = (gp_eur / cost_eur * 100) if cost_eur > 0 else None
    return {"value_eur": value_eur, "gp_eur": gp_eur, "gp_pct": gp_pct}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_portfolio_math.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/portfolio_math.py tests/test_portfolio_math.py
git commit -m "feat: add value/gain-loss calculation"
```

---

### Task 3: Analysis entry tool

**Files:**
- Create: `tools/append_analysis.py`
- Test: `tests/test_append_analysis.py`

**Interfaces:**
- Consumes: `tools.portfolio_lib.data_dir`, `tools.portfolio_lib.append_yaml_list`
- Produces (used by Task 11, and by the agent when running the `update_portfolio` workflow):
  - `analysis_yaml_path(ticker: str) -> Path`
  - `build_entry(price_change_pct: float, window: str, price_narrative: str, status: str, watch: str, today_str: str | None = None) -> dict`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_append_analysis.py
from tools.append_analysis import build_entry


def test_build_entry_has_expected_shape():
    entry = build_entry(
        price_change_pct=4.2,
        window="since 2026-09-09",
        price_narrative="Up 4% this week on strong sell-through reports.",
        status="Valuation reasonable at 22x P/E.",
        watch="Earnings call on 2026-10-15.",
        today_str="2026-09-16",
    )
    assert entry == {
        "date": "2026-09-16",
        "price_change_pct": 4.2,
        "window": "since 2026-09-09",
        "price_narrative": "Up 4% this week on strong sell-through reports.",
        "status": "Valuation reasonable at 22x P/E.",
        "watch": "Earnings call on 2026-10-15.",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_append_analysis.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.append_analysis'`

- [ ] **Step 3: Implement `tools/append_analysis.py`**

```python
import argparse
from datetime import date
from pathlib import Path

from tools.portfolio_lib import append_yaml_list, data_dir


def analysis_yaml_path(ticker: str) -> Path:
    return data_dir() / "analysis" / f"{ticker}.yaml"


def build_entry(
    price_change_pct: float,
    window: str,
    price_narrative: str,
    status: str,
    watch: str,
    today_str: str | None = None,
) -> dict:
    return {
        "date": today_str or date.today().isoformat(),
        "price_change_pct": price_change_pct,
        "window": window,
        "price_narrative": price_narrative,
        "status": status,
        "watch": watch,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--price-change-pct", type=float, required=True)
    parser.add_argument("--window", required=True)
    parser.add_argument("--price-narrative", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--watch", required=True)
    args = parser.parse_args()

    entry = build_entry(
        args.price_change_pct, args.window, args.price_narrative, args.status, args.watch
    )
    append_yaml_list(analysis_yaml_path(args.ticker), entry, "entries")
    print(f"Appended analysis entry for {args.ticker} on {entry['date']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_append_analysis.py -v`
Expected: PASS

- [ ] **Step 5: Manual verification**

Run: `PORTFOLIO_DATA_DIR=./data python -m tools.append_analysis --ticker TEST --price-change-pct 1.0 --window "test" --price-narrative "test" --status "test" --watch "test"`
Expected: prints `Appended analysis entry for TEST on <today>`; `data/analysis/TEST.yaml` is created. Delete this test file afterward (`rm data/analysis/TEST.yaml`) — it was only to prove the CLI wiring works, not real data.

- [ ] **Step 6: Commit**

```bash
git add tools/append_analysis.py tests/test_append_analysis.py
git commit -m "feat: add CLI tool for the agent to append analysis entries"
```

---

### Task 4: FX rate tool

**Files:**
- Create: `tools/fetch_fx_rate.py`
- Test: `tests/test_fetch_fx_rate.py`

**Interfaces:**
- Consumes: `tools.portfolio_lib.data_dir`
- Produces (used by Task 8, Task 10):
  - `get_rate(currency: str, today_str: str | None = None, fetch_fn=None) -> float` — returns the rate to convert 1 unit of `currency` into EUR; `1.0` when `currency == "EUR"`. `fetch_fn` defaults to `fetch_rate_live` and is injectable for tests.
  - `fetch_rate_live(currency: str) -> float` (thin real `yfinance` wrapper)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fetch_fx_rate.py
from tools.fetch_fx_rate import cache_path, get_rate


def test_eur_returns_one_without_calling_fetch_fn():
    calls = []
    rate = get_rate("EUR", fetch_fn=lambda c: calls.append(c) or 999.0)
    assert rate == 1.0
    assert calls == []


def test_fetches_and_caches_rate(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path))
    calls = []

    def fake_fetch(currency):
        calls.append(currency)
        return 0.87

    rate1 = get_rate("USD", today_str="2026-09-16", fetch_fn=fake_fetch)
    assert rate1 == 0.87
    assert calls == ["USD"]

    # second call same day: served from cache, fetch_fn not called again
    rate2 = get_rate("USD", today_str="2026-09-16", fetch_fn=fake_fetch)
    assert rate2 == 0.87
    assert calls == ["USD"]

    assert cache_path("USD").exists()


def test_refetches_on_new_day(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path))
    calls = []

    def fake_fetch(currency):
        calls.append(currency)
        return 0.87 + len(calls) * 0.01

    get_rate("USD", today_str="2026-09-16", fetch_fn=fake_fetch)
    rate2 = get_rate("USD", today_str="2026-09-17", fetch_fn=fake_fetch)
    assert calls == ["USD", "USD"]
    assert rate2 == 0.88
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_fetch_fx_rate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.fetch_fx_rate'`

- [ ] **Step 3: Implement `tools/fetch_fx_rate.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_fetch_fx_rate.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Manual verification**

Run: `python -m tools.fetch_fx_rate --currency USD` then `python -m tools.fetch_fx_rate --currency CHF`
Expected: prints a plausible EUR rate for each (roughly 0.85-0.95 range); re-running immediately should be instant (cache hit, no visible delay).

- [ ] **Step 6: Commit**

```bash
git add tools/fetch_fx_rate.py tests/test_fetch_fx_rate.py
git commit -m "feat: add daily-cached FX rate tool"
```

---

### Task 5: Price fetch tool

**Files:**
- Create: `tools/fetch_prices.py`
- Test: `tests/test_fetch_prices.py`

**Interfaces:**
- Consumes: `tools.portfolio_lib.{data_dir, load_csv_rows, append_dedup_csv}`
- Produces (used by Task 8, Task 10):
  - `price_csv_path(ticker: str) -> Path`
  - `PRICE_FIELDNAMES: list[str]` = `["date", "open", "high", "low", "close", "volume"]`
  - `compute_start_date(ticker: str, default_lookback_days: int = 30, today: date | None = None) -> date`
  - `save_prices(ticker: str, rows: list[dict]) -> int`
  - `fetch_price_history(ticker: str, start: date, end: date) -> list[dict]` (thin real `yfinance` wrapper)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fetch_prices.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_fetch_prices.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.fetch_prices'`

- [ ] **Step 3: Implement `tools/fetch_prices.py`**

```python
import argparse
from datetime import date, datetime, timedelta
from pathlib import Path

import yfinance as yf

from tools.portfolio_lib import append_dedup_csv, data_dir, load_csv_rows

PRICE_FIELDNAMES = ["date", "open", "high", "low", "close", "volume"]


def price_csv_path(ticker: str) -> Path:
    return data_dir() / "prices" / f"{ticker}.csv"


def compute_start_date(ticker: str, default_lookback_days: int = 30, today: date | None = None) -> date:
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
    rows = []
    for idx, row in df.iterrows():
        rows.append(
            {
                "date": idx.strftime("%Y-%m-%d"),
                "open": f"{row['Open']:.4f}",
                "high": f"{row['High']:.4f}",
                "low": f"{row['Low']:.4f}",
                "close": f"{row['Close']:.4f}",
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
    added = save_prices(args.ticker, rows)
    print(f"{args.ticker}: fetched {len(rows)} days, {added} new")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_fetch_prices.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Manual verification**

Run: `python -m tools.fetch_prices --ticker HON`
Expected: prints `HON: fetched ~22 days, 22 new` (30 calendar days minus weekends); `data/prices/HON.csv` contains real OHLCV rows. Re-run immediately: `HON: fetched 0 days, 0 new` (no new trading days yet).

- [ ] **Step 6: Commit**

```bash
git add tools/fetch_prices.py tests/test_fetch_prices.py
git commit -m "feat: add incremental price history fetch tool"
```

---

### Task 6: News fetch tool

**Files:**
- Create: `tools/fetch_news.py`
- Test: `tests/test_fetch_news.py`

**Interfaces:**
- Consumes: `tools.portfolio_lib.{data_dir, append_dedup_jsonl}`
- Produces (used by Task 10):
  - `news_jsonl_path(ticker: str) -> Path`
  - `google_news_rss_url(company: str) -> str`
  - `parse_feed_entries(feed) -> list[dict]` — each dict has `date, title, source, url, fetched_at`
  - `save_news(ticker: str, entries: list[dict]) -> int`
  - `fetch_news_live(ticker: str, company: str) -> list[dict]` (thin real `feedparser` wrapper)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fetch_news.py
import time

from tools.fetch_news import google_news_rss_url, parse_feed_entries, save_news, news_jsonl_path
from tools.portfolio_lib import load_jsonl_rows


class FakeFeed:
    def __init__(self, entries):
        self.entries = entries


def test_google_news_rss_url_encodes_company_name():
    url = google_news_rss_url("Honeywell International")
    assert url.startswith("https://news.google.com/rss/search?q=Honeywell")
    assert "hl=en-US" in url


def test_parse_feed_entries_extracts_fields():
    feed = FakeFeed(
        [
            {
                "title": "Honeywell raises guidance",
                "link": "https://example.com/a",
                "published": "Mon, 15 Sep 2026 10:00:00 GMT",
                "published_parsed": time.struct_time((2026, 9, 15, 10, 0, 0, 0, 0, 0)),
                "source": {"title": "Reuters"},
            }
        ]
    )
    entries = parse_feed_entries(feed)
    assert entries[0]["title"] == "Honeywell raises guidance"
    assert entries[0]["url"] == "https://example.com/a"
    assert entries[0]["date"] == "2026-09-15"
    assert entries[0]["source"] == "Reuters"
    assert "fetched_at" in entries[0]


def test_save_news_dedups_by_url(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path))
    entry = {"date": "2026-09-15", "title": "A", "source": "X", "url": "https://a", "fetched_at": "now"}
    added1 = save_news("HON", [entry])
    added2 = save_news("HON", [entry])
    assert added1 == 1
    assert added2 == 0
    assert len(load_jsonl_rows(news_jsonl_path("HON"))) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fetch_news.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.fetch_news'`

- [ ] **Step 3: Implement `tools/fetch_news.py`**

```python
import argparse
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import feedparser

from tools.portfolio_lib import append_dedup_jsonl, data_dir


def news_jsonl_path(ticker: str) -> Path:
    return data_dir() / "news" / f"{ticker}.jsonl"


def google_news_rss_url(company: str) -> str:
    query = quote_plus(company)
    return f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


def parse_feed_entries(feed) -> list[dict]:
    fetched_at = datetime.now(timezone.utc).isoformat()
    entries = []
    for entry in feed.entries:
        published = entry.get("published", "")
        parsed = entry.get("published_parsed")
        if parsed:
            date_str = datetime(*parsed[:6]).date().isoformat()
        else:
            date_str = published[:10] if published else ""

        source = entry.get("source", "")
        source_title = source.get("title", "") if isinstance(source, dict) else str(source)

        entries.append(
            {
                "date": date_str,
                "title": entry.get("title", ""),
                "source": source_title,
                "url": entry.get("link", ""),
                "fetched_at": fetched_at,
            }
        )
    return entries


def fetch_news_live(ticker: str, company: str) -> list[dict]:
    feed = feedparser.parse(google_news_rss_url(company))
    return parse_feed_entries(feed)


def save_news(ticker: str, entries: list[dict]) -> int:
    return append_dedup_jsonl(news_jsonl_path(ticker), entries, "url")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--company", required=True)
    args = parser.parse_args()

    entries = fetch_news_live(args.ticker, args.company)
    added = save_news(args.ticker, entries)
    print(f"{args.ticker}: fetched {len(entries)} headlines, {added} new")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fetch_news.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Manual verification**

Run: `python -m tools.fetch_news --ticker HON --company "Honeywell International"`
Expected: prints a headline count > 0 in most cases; `data/news/HON.jsonl` has readable headlines with plausible titles/URLs.

- [ ] **Step 6: Commit**

```bash
git add tools/fetch_news.py tests/test_fetch_news.py
git commit -m "feat: add Google News RSS fetch tool"
```

---

### Task 7: Fundamentals fetch tool

**Files:**
- Create: `tools/fetch_fundamentals.py`
- Test: `tests/test_fetch_fundamentals.py`

**Interfaces:**
- Consumes: `tools.portfolio_lib.{data_dir, append_yaml_list, load_yaml_list, latest_by_date}`
- Produces (used by Task 10):
  - `fundamentals_yaml_path(ticker: str) -> Path`
  - `FUNDAMENTALS_FIELDS: dict[str, str]`
  - `extract_fundamentals(info: dict, today_str: str | None = None) -> dict`
  - `latest_fundamentals_snapshot(ticker: str) -> dict | None`
  - `save_fundamentals(ticker: str, snapshot: dict) -> None`
  - `fetch_info_live(ticker: str) -> dict` (thin real `yfinance` wrapper)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fetch_fundamentals.py
from tools.fetch_fundamentals import extract_fundamentals, latest_fundamentals_snapshot, save_fundamentals


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
    assert snapshot["fifty_two_week_low"] is None
    assert snapshot["fifty_two_week_high"] is None


def test_save_and_load_latest_fundamentals_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path))
    save_fundamentals("HON", extract_fundamentals({"trailingPE": 20.0}, today_str="2026-09-01"))
    save_fundamentals("HON", extract_fundamentals({"trailingPE": 22.0}, today_str="2026-09-16"))

    latest = latest_fundamentals_snapshot("HON")
    assert latest["date"] == "2026-09-16"
    assert latest["pe_ratio"] == 22.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_fetch_fundamentals.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.fetch_fundamentals'`

- [ ] **Step 3: Implement `tools/fetch_fundamentals.py`**

```python
import argparse
from datetime import date
from pathlib import Path

import yfinance as yf

from tools.portfolio_lib import append_yaml_list, data_dir, latest_by_date, load_yaml_list

FUNDAMENTALS_FIELDS = {
    "pe_ratio": "trailingPE",
    "forward_pe": "forwardPE",
    "debt_to_equity": "debtToEquity",
    "dividend_yield": "dividendYield",
    "market_cap": "marketCap",
    "profit_margin": "profitMargins",
    "fifty_two_week_low": "fiftyTwoWeekLow",
    "fifty_two_week_high": "fiftyTwoWeekHigh",
}


def fundamentals_yaml_path(ticker: str) -> Path:
    return data_dir() / "fundamentals" / f"{ticker}.yaml"


def extract_fundamentals(info: dict, today_str: str | None = None) -> dict:
    snapshot = {"date": today_str or date.today().isoformat()}
    for local_key, info_key in FUNDAMENTALS_FIELDS.items():
        snapshot[local_key] = info.get(info_key)
    return snapshot


def fetch_info_live(ticker: str) -> dict:
    return yf.Ticker(ticker).info


def save_fundamentals(ticker: str, snapshot: dict) -> None:
    append_yaml_list(fundamentals_yaml_path(ticker), snapshot, "snapshots")


def latest_fundamentals_snapshot(ticker: str) -> dict | None:
    return latest_by_date(load_yaml_list(fundamentals_yaml_path(ticker), "snapshots"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    args = parser.parse_args()

    info = fetch_info_live(args.ticker)
    snapshot = extract_fundamentals(info)
    save_fundamentals(args.ticker, snapshot)
    print(f"{args.ticker}: P/E {snapshot['pe_ratio']}, Debt/Equity {snapshot['debt_to_equity']}, Div Yield {snapshot['dividend_yield']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_fetch_fundamentals.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Manual verification**

Run: `python -m tools.fetch_fundamentals --ticker HON`
Expected: prints plausible P/E, debt-to-equity, and dividend yield values; `data/fundamentals/HON.yaml` has one snapshot. Also try `--ticker VWRL` (the ETF) — expect `None` for most fields since ETFs don't report company fundamentals; confirm the tool doesn't crash on that.

- [ ] **Step 6: Commit**

```bash
git add tools/fetch_fundamentals.py tests/test_fetch_fundamentals.py
git commit -m "feat: add fundamentals snapshot fetch tool"
```

---

### Task 8: Portfolio snapshot/history tool — includes real-data G/P validation

**Files:**
- Create: `tools/record_snapshot.py`
- Test: `tests/test_record_snapshot.py`

**Interfaces:**
- Consumes: `tools.portfolio_lib.{data_dir, load_csv_rows, append_dedup_csv, latest_by_date}`, `tools.portfolio_math.compute_value_and_gp`, `tools.fetch_prices.price_csv_path`, `tools.fetch_fx_rate.get_rate`, `tools.portfolio_lib.load_portfolio`
- Produces (used by Task 10, Task 11):
  - `history_csv_path() -> Path`
  - `HISTORY_FIELDNAMES: list[str]`
  - `latest_price(ticker: str) -> dict | None`
  - `build_snapshot_row(holding: dict, price_row: dict, fx_rate: float, today_str: str | None = None) -> dict`
  - `latest_history_by_ticker() -> dict[str, dict]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_record_snapshot.py
from tools.record_snapshot import build_snapshot_row, latest_history_by_ticker, history_csv_path
from tools.portfolio_lib import append_dedup_csv


def test_build_snapshot_row_computes_value_and_gp():
    holding = {"ticker": "SAN", "shares": 20, "avg_cost_local": 50.0, "currency": "EUR"}
    price_row = {"date": "2026-09-16", "close": "60.98"}

    row = build_snapshot_row(holding, price_row, fx_rate=1.0, today_str="2026-09-16")

    assert row["ticker"] == "SAN"
    assert row["date"] == "2026-09-16"
    assert float(row["value_eur"]) > 0
    assert row["gp_pct"] != ""


def test_build_snapshot_row_zero_avg_cost_leaves_gp_pct_blank():
    holding = {"ticker": "KD", "shares": 3, "avg_cost_local": 0.0, "currency": "USD"}
    price_row = {"date": "2026-09-16", "close": "90.925"}

    row = build_snapshot_row(holding, price_row, fx_rate=0.9, today_str="2026-09-16")

    assert row["gp_pct"] == ""


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_record_snapshot.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.record_snapshot'`

- [ ] **Step 3: Implement `tools/record_snapshot.py`**

```python
import argparse
from datetime import date
from pathlib import Path

from tools.fetch_fx_rate import get_rate
from tools.fetch_prices import price_csv_path
from tools.portfolio_lib import append_dedup_csv, data_dir, latest_by_date, load_csv_rows, load_portfolio
from tools.portfolio_math import compute_value_and_gp

HISTORY_FIELDNAMES = [
    "date", "ticker", "shares", "price_local", "currency",
    "value_eur", "avg_cost_local", "gp_eur", "gp_pct",
]


def history_csv_path() -> Path:
    return data_dir() / "portfolio_history.csv"


def latest_price(ticker: str) -> dict | None:
    rows = load_csv_rows(price_csv_path(ticker))
    return latest_by_date(rows) if rows else None


def build_snapshot_row(holding: dict, price_row: dict, fx_rate: float, today_str: str | None = None) -> dict:
    result = compute_value_and_gp(
        shares=holding["shares"],
        price_local=float(price_row["close"]),
        avg_cost_local=holding["avg_cost_local"],
        fx_rate=fx_rate,
    )
    return {
        "date": today_str or date.today().isoformat(),
        "ticker": holding["ticker"],
        "shares": holding["shares"],
        "price_local": price_row["close"],
        "currency": holding["currency"],
        "value_eur": f"{result['value_eur']:.2f}",
        "avg_cost_local": holding["avg_cost_local"],
        "gp_eur": f"{result['gp_eur']:.2f}",
        "gp_pct": "" if result["gp_pct"] is None else f"{result['gp_pct']:.2f}",
    }


def latest_history_by_ticker() -> dict[str, dict]:
    rows = load_csv_rows(history_csv_path())
    by_ticker: dict[str, list[dict]] = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], []).append(r)
    return {t: latest_by_date(rs) for t, rs in by_ticker.items()}


def main():
    for holding in load_portfolio():
        price_row = latest_price(holding["ticker"])
        if price_row is None:
            print(f"{holding['ticker']}: no price data yet, run fetch_prices first — skipping")
            continue
        fx_rate = get_rate(holding["currency"])
        row = build_snapshot_row(holding, price_row, fx_rate)
        append_dedup_csv(history_csv_path(), [row], ["date", "ticker"], HISTORY_FIELDNAMES)
        gp_pct_display = row["gp_pct"] or "n/a"
        print(f"{holding['ticker']}: value {row['value_eur']} EUR, G/P {row['gp_eur']} EUR ({gp_pct_display}%)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_record_snapshot.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Real-data validation (critical — validates the `avg_cost_local` currency assumption)**

Run, from the repo root, for at least 3 holdings the owner pasted values for
(recommend `HON`, `MCD`, `BAC` — a spread of small/large G/P):
```bash
python -m tools.fetch_prices --ticker HON
python -m tools.fetch_prices --ticker MCD
python -m tools.fetch_prices --ticker BAC
python -m tools.record_snapshot
```
Compare the printed `value` and `G/P` figures against the numbers the owner
pasted in chat (e.g. HON: Valor ~1500.00, G/P Potencial ~+250.00
(+20.00%)). Note current prices will differ slightly from the pasted
snapshot's timestamp, so match on the *shape* (same sign, same order of
magnitude, roughly the same percentage) rather than exact figures.

- **If it roughly matches:** the `avg_cost_local`-is-in-trading-currency
  assumption holds. Proceed.
- **If it's off by a large, consistent factor** (e.g. G/P is way too
  small or negative when it should be strongly positive): the breakeven price is
  likely already EUR-denominated. Fix by changing `build_snapshot_row`
  to use `fx_rate=1.0` for the cost-basis leg specifically (i.e. treat
  `avg_cost_local * shares` as already in EUR, only convert the current
  `value_eur` leg with the real FX rate). Re-run the comparison. Update
  the assumption note in `data/portfolio.yaml`'s header comment and in
  the spec's Data model section to reflect whichever assumption won.

- [ ] **Step 6: Commit**

```bash
git add tools/record_snapshot.py tests/test_record_snapshot.py
git commit -m "feat: add portfolio value/gain-loss history snapshot tool"
```

If Step 5 required a fix, include that fix in this commit (or a
follow-up commit) and update the spec doc:
```bash
git add data/portfolio.yaml docs/superpowers/specs/2026-09-16-portfolio-tracker-design.md tools/record_snapshot.py
git commit -m "fix: correct avg_cost_local currency assumption based on real data"
```

---

### Task 9: Google Cloud OAuth setup + shared auth module

**Files:**
- Create: `tools/google_auth.py`

**Interfaces:**
- Consumes: `tools.portfolio_lib.repo_root`
- Produces (used by Task 10, Task 11):
  - `SCOPES: list[str]`
  - `credentials_path() -> Path`
  - `token_path() -> Path`
  - `get_credentials() -> google.oauth2.credentials.Credentials`

- [ ] **Step 1: Walk the owner through Google Cloud setup (interactive, not code)**

Ask the owner to, in a browser:
1. Go to https://console.cloud.google.com/ and create a new project
   (e.g. "portfolio-tracker").
2. In "APIs & Services" → "Library", enable: **Google Sheets API**,
   **Google Docs API**, and **Google Drive API**.
3. In "APIs & Services" → "OAuth consent screen", choose "External",
   fill in the minimal required fields (app name, support email), and
   add himself as a test user.
4. In "APIs & Services" → "Credentials" → "Create Credentials" → "OAuth
   client ID" → Application type **Desktop app**. Download the resulting
   JSON.
5. Save that downloaded file as `credentials.json` in the project root
   (`credentials.json` in the repo root).
   It's already gitignored.

- [ ] **Step 2: Implement `tools/google_auth.py`**

```python
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from tools.portfolio_lib import repo_root

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]


def credentials_path() -> Path:
    return repo_root() / "credentials.json"


def token_path() -> Path:
    return repo_root() / "token.json"


def get_credentials() -> Credentials:
    creds = None
    if token_path().exists():
        creds = Credentials.from_authorized_user_file(str(token_path()), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path()), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path().write_text(creds.to_json(), encoding="utf-8")

    return creds


def main():
    creds = get_credentials()
    print("Google auth OK. Token valid:", creds.valid)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Manual verification**

Run: `python -m tools.google_auth`
Expected: a browser window opens asking the owner to log in and consent to
the requested scopes (Sheets, Docs, Drive.file). After consenting,
`token.json` is created in the project root and the script prints
`Google auth OK. Token valid: True`. Re-run — expect no browser prompt
this time (token reused/refreshed silently).

No automated test for this task: it wraps an interactive OAuth flow that
can't be meaningfully unit tested without mocking the entire Google auth
library, which would test the mock, not the integration. The manual
verification above is the real test.

- [ ] **Step 4: Commit**

```bash
git add tools/google_auth.py
git commit -m "feat: add shared Google OAuth credential helper"
```

(`credentials.json` and `token.json` stay local — already gitignored.)

---

### Task 10: Google Sheet sync tool

**Files:**
- Create: `tools/sync_google_sheet.py`
- Test: `tests/test_sync_google_sheet.py`

**Interfaces:**
- Consumes: `tools.portfolio_lib.{load_portfolio, load_csv_rows, load_jsonl_rows}`, `tools.fetch_prices.price_csv_path`, `tools.fetch_news.news_jsonl_path`, `tools.fetch_fundamentals.latest_fundamentals_snapshot`, `tools.record_snapshot.latest_history_by_ticker`, `tools.google_auth.get_credentials`
- Produces: `build_overview_rows(...)`, `build_ticker_tab_rows(...)`, `OVERVIEW_HEADER`, `TICKER_TAB_HEADER`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sync_google_sheet.py
from tools.sync_google_sheet import build_overview_rows, build_ticker_tab_rows


def test_build_overview_rows_includes_header_and_one_row_per_holding():
    holdings = [
        {"ticker": "HON", "company": "Honeywell International", "shares": 10, "currency": "USD", "avg_cost_local": 120.50, "is_etf": False},
    ]
    latest_history = {"HON": {"price_local": "163.90", "value_eur": "1500.00", "gp_eur": "250.00", "gp_pct": "20.00", "date": "2026-09-16"}}
    latest_fundamentals = {"HON": {"pe_ratio": 22.4, "dividend_yield": 0.028}}

    rows = build_overview_rows(holdings, latest_history, latest_fundamentals)

    assert rows[0][0] == "Ticker"
    assert rows[1][0] == "HON"
    assert rows[1][5] == "1500.00"  # Value (EUR) column


def test_build_ticker_tab_rows_joins_news_by_date():
    price_rows = [{"date": "2026-09-15", "close": "160.0"}, {"date": "2026-09-16", "close": "163.9"}]
    news_entries = [{"date": "2026-09-16", "title": "Honeywell raises guidance", "url": "https://x", "source": "Reuters", "fetched_at": "now"}]

    rows = build_ticker_tab_rows("HON", price_rows, news_entries)

    assert rows[0] == ["Date", "Close", "News"]
    assert rows[1] == ["2026-09-15", "160.0", ""]
    assert rows[2] == ["2026-09-16", "163.9", "Honeywell raises guidance"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sync_google_sheet.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.sync_google_sheet'`

- [ ] **Step 3: Implement `tools/sync_google_sheet.py`**

```python
import argparse

import gspread

from tools.fetch_fundamentals import latest_fundamentals_snapshot
from tools.fetch_news import news_jsonl_path
from tools.fetch_prices import price_csv_path
from tools.google_auth import get_credentials
from tools.portfolio_lib import load_csv_rows, load_jsonl_rows, load_portfolio
from tools.record_snapshot import latest_history_by_ticker

SHEET_NAME = "Portfolio Tracker"

OVERVIEW_HEADER = [
    "Ticker", "Company", "Shares", "Price (local)", "Currency",
    "Value (EUR)", "Avg Cost (local)", "G/P (EUR)", "G/P %",
    "P/E", "Div Yield", "Last Updated",
]

TICKER_TAB_HEADER = ["Date", "Close", "News"]


def build_overview_rows(holdings: list[dict], latest_history: dict[str, dict], latest_fundamentals: dict[str, dict]) -> list[list]:
    rows = [OVERVIEW_HEADER]
    for h in holdings:
        hist = latest_history.get(h["ticker"], {})
        fund = latest_fundamentals.get(h["ticker"], {})
        rows.append(
            [
                h["ticker"], h["company"], h["shares"],
                hist.get("price_local", ""), h["currency"],
                hist.get("value_eur", ""), h["avg_cost_local"],
                hist.get("gp_eur", ""), hist.get("gp_pct", ""),
                fund.get("pe_ratio", ""), fund.get("dividend_yield", ""),
                hist.get("date", ""),
            ]
        )
    return rows


def build_ticker_tab_rows(ticker: str, price_rows: list[dict], news_entries: list[dict]) -> list[list]:
    news_by_date: dict[str, list[str]] = {}
    for n in news_entries:
        news_by_date.setdefault(n["date"], []).append(n["title"])

    rows = [TICKER_TAB_HEADER]
    for p in sorted(price_rows, key=lambda r: r["date"]):
        headlines = "; ".join(news_by_date.get(p["date"], []))
        rows.append([p["date"], p["close"], headlines])
    return rows


def get_or_create_spreadsheet(client, title: str = SHEET_NAME):
    try:
        return client.open(title)
    except gspread.SpreadsheetNotFound:
        return client.create(title)


def write_sheet(spreadsheet, overview_rows: list[list], ticker_tabs: dict[str, list[list]]) -> None:
    overview_ws = spreadsheet.sheet1
    overview_ws.update_title("Overview")
    overview_ws.clear()
    overview_ws.update(overview_rows)

    existing_titles = {ws.title for ws in spreadsheet.worksheets()}
    for ticker, rows in ticker_tabs.items():
        if ticker in existing_titles:
            ws = spreadsheet.worksheet(ticker)
            ws.clear()
        else:
            ws = spreadsheet.add_worksheet(title=ticker, rows=max(len(rows), 100), cols=len(rows[0]) if rows else 10)
        ws.update(rows)


def main():
    holdings = load_portfolio()
    latest_history = latest_history_by_ticker()
    latest_fundamentals = {h["ticker"]: (latest_fundamentals_snapshot(h["ticker"]) or {}) for h in holdings}

    overview_rows = build_overview_rows(holdings, latest_history, latest_fundamentals)
    ticker_tabs = {}
    for h in holdings:
        price_rows = load_csv_rows(price_csv_path(h["ticker"]))
        news_entries = load_jsonl_rows(news_jsonl_path(h["ticker"]))
        if price_rows:
            ticker_tabs[h["ticker"]] = build_ticker_tab_rows(h["ticker"], price_rows, news_entries)

    client = gspread.authorize(get_credentials())
    spreadsheet = get_or_create_spreadsheet(client)
    write_sheet(spreadsheet, overview_rows, ticker_tabs)
    print(f"Synced {len(holdings)} holdings to Google Sheet: {spreadsheet.url}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sync_google_sheet.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Manual verification**

Prerequisite: Task 9 complete (`token.json` exists). Ensure at least
`HON`, `MCD`, `BAC` have price/fundamentals data from earlier manual
verification steps; run `fetch_prices`/`fetch_fundamentals`/`fetch_news`
for the rest of the holdings in `data/portfolio.yaml` if not already
done, then `python -m tools.record_snapshot`.

Run: `python -m tools.sync_google_sheet`
Expected: prints a Google Sheets URL; opening it shows an "Overview" tab
with one row per holding (ticker, value, G/P, P/E, etc.) and a tab per
ticker with date-indexed price history and news headlines.

- [ ] **Step 6: Commit**

```bash
git add tools/sync_google_sheet.py tests/test_sync_google_sheet.py
git commit -m "feat: add Google Sheet sync tool"
```

---

### Task 11: Google Doc summary sync tool

**Files:**
- Create: `tools/sync_summary_doc.py`
- Test: `tests/test_sync_summary_doc.py`

**Interfaces:**
- Consumes: `tools.portfolio_lib.{load_portfolio, load_yaml_list, latest_by_date}`, `tools.append_analysis.analysis_yaml_path`, `tools.record_snapshot.latest_history_by_ticker`, `tools.google_auth.get_credentials`
- Produces: `build_summary_sections(...)`, `DOC_TITLE`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sync_summary_doc.py
from tools.sync_summary_doc import build_summary_sections


def test_build_summary_sections_includes_status_and_watch():
    holdings = [{"ticker": "HON", "company": "Honeywell International", "shares": 10}]
    latest_analysis = {
        "HON": {
            "status": "Valuation reasonable at 22x P/E.",
            "price_narrative": "Up 4% this week on strong sell-through.",
            "watch": "Earnings call 2026-10-15.",
        }
    }
    latest_history = {"HON": {"value_eur": "1500.00", "gp_eur": "250.00", "gp_pct": "20.00"}}

    sections = build_summary_sections(holdings, latest_analysis, latest_history)

    assert len(sections) == 1
    assert "Honeywell International (HON)" in sections[0]
    assert "Valuation reasonable at 22x P/E." in sections[0]
    assert "Earnings call 2026-10-15." in sections[0]
    assert "250.00" in sections[0]


def test_build_summary_sections_handles_missing_analysis():
    holdings = [{"ticker": "KD", "company": "Kyndryl Holdings", "shares": 3}]
    sections = build_summary_sections(holdings, {}, {})
    assert "No status recorded yet." in sections[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sync_summary_doc.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.sync_summary_doc'`

- [ ] **Step 3: Implement `tools/sync_summary_doc.py`**

```python
from googleapiclient.discovery import build

from tools.google_auth import get_credentials
from tools.portfolio_lib import latest_by_date, load_portfolio, load_yaml_list
from tools.append_analysis import analysis_yaml_path
from tools.record_snapshot import latest_history_by_ticker

DOC_TITLE = "Portfolio Summary"


def build_summary_sections(holdings: list[dict], latest_analysis: dict[str, dict], latest_history: dict[str, dict]) -> list[str]:
    sections = []
    for h in holdings:
        analysis = latest_analysis.get(h["ticker"], {})
        hist = latest_history.get(h["ticker"], {})
        lines = [
            f"{h['company']} ({h['ticker']})",
            f"Shares: {h['shares']}  |  Value: {hist.get('value_eur', 'n/a')} EUR  |  G/P: {hist.get('gp_eur', 'n/a')} EUR ({hist.get('gp_pct', 'n/a')}%)",
            f"Status: {analysis.get('status', 'No status recorded yet.')}",
            f"Recent move: {analysis.get('price_narrative', 'No narrative recorded yet.')}",
            f"Watch: {analysis.get('watch', 'Nothing flagged.')}",
        ]
        sections.append("\n".join(lines))
    return sections


def get_or_create_doc(docs_service, drive_service, title: str = DOC_TITLE):
    results = drive_service.files().list(
        q=f"name='{title}' and mimeType='application/vnd.google-apps.document' and trashed=false"
    ).execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    doc = docs_service.documents().create(body={"title": title}).execute()
    return doc["documentId"]


def write_doc(docs_service, doc_id: str, sections: list[str]) -> None:
    doc = docs_service.documents().get(documentId=doc_id).execute()
    end_index = doc["body"]["content"][-1]["endIndex"]

    requests = []
    if end_index > 2:
        requests.append({"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index - 1}}})

    text = "\n\n".join(sections) + "\n"
    requests.append({"insertText": {"location": {"index": 1}, "text": text}})

    docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()


def main():
    holdings = load_portfolio()
    latest_analysis = {
        h["ticker"]: (latest_by_date(load_yaml_list(analysis_yaml_path(h["ticker"]), "entries")) or {})
        for h in holdings
    }
    latest_history = latest_history_by_ticker()

    sections = build_summary_sections(holdings, latest_analysis, latest_history)

    creds = get_credentials()
    docs_service = build("docs", "v1", credentials=creds)
    drive_service = build("drive", "v3", credentials=creds)

    doc_id = get_or_create_doc(docs_service, drive_service)
    write_doc(docs_service, doc_id, sections)
    print(f"Synced summary for {len(holdings)} holdings to Google Doc: https://docs.google.com/document/d/{doc_id}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sync_summary_doc.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Manual verification**

Prerequisite: at least one `data/analysis/<TICKER>.yaml` exists (from
Task 3's manual step, or write a real one now — see Task 12).

Run: `python -m tools.sync_summary_doc`
Expected: prints a Google Doc URL; opening it shows one section per
holding with status, recent move, G/P, and watch items in readable
prose.

- [ ] **Step 6: Commit**

```bash
git add tools/sync_summary_doc.py tests/test_sync_summary_doc.py
git commit -m "feat: add Google Doc summary sync tool"
```

---

### Task 12: `update_portfolio` workflow + dry run

**Files:**
- Create: `workflows/update_portfolio.md`

**Interfaces:**
- Consumes: every tool from Tasks 3-11 (documents the CLI invocation of each).

- [ ] **Step 1: Write the workflow SOP**

```markdown
# Workflow: Update Portfolio

**Trigger:** the owner asks to update his portfolio (e.g. "update my
portfolio", "what's new with my stocks").

**Objective:** Refresh price/news/fundamentals data for every holding,
compute current value and gain/loss, write a short narrative and status
per holding, and sync everything to Google Sheets and the summary Doc.

**Steps:**

1. Read `data/portfolio.yaml` (via `tools.portfolio_lib.load_portfolio`)
   to get the current holding list.

2. For each holding, run in order:
   ```
   python -m tools.fetch_prices --ticker <TICKER>
   python -m tools.fetch_news --ticker <TICKER> --company "<COMPANY>"
   python -m tools.fetch_fundamentals --ticker <TICKER>
   ```

3. For each currency present among the holdings (USD, CHF, EUR), the FX
   rate is fetched automatically by `record_snapshot` in the next step
   — no separate step needed.

4. Run:
   ```
   python -m tools.record_snapshot
   ```
   This computes value/G-P per holding and appends to
   `data/portfolio_history.csv`. Note the printed value/G-P for each
   holding — you'll use it in the next step.

5. For each holding, the agent reviews:
   - the price change since the last recorded snapshot (from
     `data/portfolio_history.csv`),
   - the headlines fetched in step 2 (`data/news/<TICKER>.jsonl`),
   - the fundamentals snapshot (`data/fundamentals/<TICKER>.yaml`),

   and writes a short narrative, a status line, and a "biggest thing to
   watch" note. Ground every claim in the fetched data — if no relevant
   news turned up, say so explicitly rather than inventing a cause.
   Append via:
   ```
   python -m tools.append_analysis --ticker <TICKER> \
     --price-change-pct <PCT> --window "<WINDOW>" \
     --price-narrative "<NARRATIVE>" --status "<STATUS>" --watch "<WATCH>"
   ```

6. Run:
   ```
   python -m tools.sync_google_sheet
   python -m tools.sync_summary_doc
   ```

7. Report a short summary back to the owner in chat: which holdings moved
   the most (up and down), the one-line reason where known, and
   anything flagged under "watch".

**Error handling:**
- If a fetch tool errors (rate limit, network, ticker not found): report
  the specific failure to the owner, do not fabricate data for that holding,
  and continue with the remaining holdings.
- If `sync_google_sheet` or `sync_summary_doc` fails (e.g. expired
  auth): local data is already saved from steps 2-5, so nothing is
  lost. Tell the owner to re-run `python -m tools.google_auth` to refresh
  the token, then re-run the sync step alone.

**Notes for future refinement:** update this section as real runs
surface rate limits, feed quirks, or auth edge cases (per the
self-improvement loop in `CLAUDE.md`).
```

- [ ] **Step 2: Dry run against 2 real holdings**

Pick two holdings not yet fully exercised in earlier manual verification
(e.g. `AMZN` and `NOVN`). Follow the workflow steps above by hand for
just those two tickers, end to end (fetch → record_snapshot → write a
real analysis entry → sync). Confirm:
- `data/analysis/AMZN.yaml` and `data/analysis/NOVN.yaml` contain a
  real, grounded entry (not placeholder text).
- The Google Sheet's Overview tab and the two tickers' tabs reflect the
  new data.
- The Google Doc's summary includes real sections for both.

Fix anything that breaks (tool bug, unclear workflow step) before
proceeding, and update the workflow doc with what was learned.

- [ ] **Step 3: Commit**

```bash
git add workflows/update_portfolio.md
git commit -m "docs: add update_portfolio workflow SOP"
```

---

### Task 13: `add_holding` workflow + dry run

**Files:**
- Create: `workflows/add_holding.md`

- [ ] **Step 1: Write the workflow SOP**

```markdown
# Workflow: Add / Update a Holding

**Trigger:** the owner mentions a buy, sell, or share-count change in chat
(e.g. "I bought 5 more shares of AAPL", "I sold my Bristol-Myers position").

**Objective:** Keep `data/portfolio.yaml` accurate, and make sure a new
position gets its initial data pulled immediately rather than waiting
for the next full `update_portfolio` run.

**Steps:**

1. Determine what changed:
   - **New position:** need ticker, company name, ISIN (optional),
     exchange, currency, shares, and cost basis (`avg_cost_local`) — ask
     the owner for whatever isn't given.
   - **Existing position, shares changed:** update `shares` for that
     ticker.
   - **Position closed:** remove the holding entry entirely (or move it
     to a `notes` field noting it was closed, if the owner wants history
     kept — ask which he prefers).

2. Edit `data/portfolio.yaml` directly (it's simple structured YAML —
   no dedicated tool needed for this step, per the design spec's YAGNI
   call).

3. If it's a **new ticker**, run the full per-holding sequence from
   `update_portfolio.md` steps 2, 4-6 scoped to just that ticker:
   ```
   python -m tools.fetch_prices --ticker <TICKER>
   python -m tools.fetch_news --ticker <TICKER> --company "<COMPANY>"
   python -m tools.fetch_fundamentals --ticker <TICKER>
   python -m tools.record_snapshot
   python -m tools.append_analysis --ticker <TICKER> ...
   python -m tools.sync_google_sheet
   python -m tools.sync_summary_doc
   ```

4. Confirm the change with the owner in chat (new share count, or the new
   position now showing up in the Sheet/Doc).

**Error handling:** same as `update_portfolio.md` — report fetch
failures rather than guessing; local `portfolio.yaml` edit always
succeeds independent of any API being reachable.
```

- [ ] **Step 2: Dry run**

Simulate a small, reversible change: temporarily bump `AMZN` shares by 1
in `data/portfolio.yaml`, run the new-ticker-equivalent steps (steps 3
above, but it's an existing ticker so just re-run
`record_snapshot`/`sync_google_sheet` to confirm the updated share count
flows through to the Overview tab's value/G-P). Then revert the share
count back to its real value (26) and re-sync so the Sheet reflects
reality again.

- [ ] **Step 3: Commit**

```bash
git add workflows/add_holding.md
git commit -m "docs: add add_holding workflow SOP"
```

---

### Task 14: Full end-to-end run on all real holdings

**Files:** none created — this is a verification/wrap-up task.

- [ ] **Step 1: Run the full `update_portfolio` workflow for all holdings**

Loop through every holding in `data/portfolio.yaml` (every stock and
ETF) following `workflows/update_portfolio.md` steps 1-6. For each,
write a real, data-grounded analysis entry (price narrative + status +
watch) — this is the first time every holding gets a genuine narrative,
not just the handful used for manual tool verification earlier.

- [ ] **Step 2: Verify the deliverables**

- Google Sheet: Overview tab has a row per holding with plausible values;
  spot-check 2-3 ticker tabs have price history + news.
- Google Doc: has a section per holding, each with real (non-placeholder)
  status/narrative/watch text.
- `data/portfolio_history.csv` has one row per holding for today's date.

- [ ] **Step 3: Report to the owner**

Summarize in chat: total portfolio value (EUR), overall G/P, which 2-3
holdings moved most, and anything flagged as worth watching. Share the
Sheet and Doc links.

- [ ] **Step 4: Note any workflow refinements needed**

If any tool broke, was slow, or hit a rate limit during the full run
across all holdings, fix it now and update the relevant workflow doc
per the self-improvement loop in `CLAUDE.md`, then commit.

```bash
git add -A
git commit -m "fix: address issues found during full-portfolio dry run"
```

(Only if fixes were needed — skip this commit if the full run was clean.)
