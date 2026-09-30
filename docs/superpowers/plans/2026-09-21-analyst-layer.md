# Analyst Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every holding a committed verdict (Add / Hold / Stop adding) and business view (Bullish / Neutral / Bearish), backed by four deterministic strategy-tuned sub-scores, plus a ranked "where your next euro goes" table in both deliverables.

**Architecture:** A pure scoring engine (`tools/analyst.py`) computes dividend-safety, quality, valuation and portfolio-fit sub-scores from already-fetched fundamentals plus the existing allocation weights, and maps them to verdicts. `tools/append_analysis.py` gains the agent's judgment fields with a code-enforced override guardrail. The two sync tools render the results; nothing in the existing scoring, Rating or technical layers changes.

**Tech Stack:** Python 3, PyYAML, gspread (Sheets API v4), google-api-python-client (Docs API v1), pytest.

**Spec:** `docs/superpowers/specs/2026-09-21-analyst-layer-design.md`

## Global Constraints

- Run from the repo root. Tools run as modules: `python -m tools.<name>`. Tests: `python -m pytest`.
- NEVER read, write, or regenerate `data/portfolio.yaml`. Tests must never touch the real `data/` directory (the autouse fixture in `conftest.py` sandboxes `PORTFOLIO_DATA_DIR`; don't defeat it).
- Do NOT run `python -m tools.sync_google_sheet` or `python -m tools.sync_summary_doc` — they write to the owner's live Sheet/Doc and need OAuth. Verification is pytest only; the controller does the live run.
- Verdict vocabulary is exactly `Add`, `Hold`, `Stop adding`, `Insufficient data`. There is NO "Sell" verdict, ever. Business views are exactly `Bullish`, `Neutral`, `Bearish`, `Insufficient data`. Confidence is exactly `high`, `medium`, `low`.
- Band boundaries are inclusive at the bottom: add_score ≥ 65 → Add; ≥ 45 → Hold; below → Stop adding. business_score ≥ 60 → Bullish; ≥ 40 → Neutral; below → Bearish.
- Sub-score weights: dividend safety 0.30, quality 0.30, valuation 0.25, fit 0.15, renormalized over whichever components exist.
- A missing input is "component unavailable", never zero. A score with no available components returns `None`.
- Nothing in `tools/scoring.py` (Rating, STATUS_BANDS, the 4 dimension scores) or `tools/technicals.py` changes.
- Sheets locale is es_ES: no new `CUSTOM_FORMULA` conditional-format rules (use `TEXT_STARTS_WITH` / `NUMBER_GREATER` / `NUMBER_LESS`).
- Commit messages end with a blank line then `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

### Task 1: Fetch the extra fundamentals

**Files:**
- Modify: `tools/fetch_fundamentals.py` (the `FUNDAMENTALS_FIELDS` dict, lines 14-31)
- Test: `tests/test_fetch_fundamentals.py`

**Interfaces:**
- Produces: `FUNDAMENTALS_FIELDS` gains 13 keys; `extract_fundamentals(info, today_str)` therefore stores them when present. Later tasks read these keys off a fundamentals snapshot dict: `payout_ratio`, `dividend_rate`, `five_year_avg_dividend_yield`, `free_cashflow`, `shares_outstanding`, `revenue_growth`, `earnings_growth`, `operating_margins`, `current_ratio`, `price_to_book`, `target_mean_price`, `recommendation_key`, `beta`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fetch_fundamentals.py`:

```python
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
```

(Check the imports at the top of the file; add `extract_fundamentals` to the existing import if it isn't already there.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fetch_fundamentals.py -v`
Expected: FAIL — `KeyError: 'payout_ratio'`.

- [ ] **Step 3: Add the fields**

In `tools/fetch_fundamentals.py`, extend `FUNDAMENTALS_FIELDS` — add these entries after the existing `"country": "country",` line, keeping the dict's existing style:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_fetch_fundamentals.py -v` then `python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/fetch_fundamentals.py tests/test_fetch_fundamentals.py
git commit -m "feat: fetch dividend safety and quality fundamentals

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Scoring engine (`tools/analyst.py`)

**Files:**
- Create: `tools/analyst.py`
- Test: `tests/test_analyst.py`

**Interfaces:**
- Consumes (Task 1): fundamentals snapshot keys listed above. Also consumes the existing `tools/allocation.py` output shape: `compute_allocation(...)["positions"]` items carry `ticker`, `weight_pct`, `sector`; `["sectors"]` items carry `name`, `weight_pct`.
- Produces:
  - Constants: `VERDICT_ADD = "Add"`, `VERDICT_HOLD = "Hold"`, `VERDICT_STOP = "Stop adding"`, `VERDICT_INSUFFICIENT = "Insufficient data"`, `VERDICTS`, `VIEW_BULLISH = "Bullish"`, `VIEW_NEUTRAL = "Neutral"`, `VIEW_BEARISH = "Bearish"`, `BUSINESS_VIEWS`, `CONFIDENCE_LEVELS = ["high", "medium", "low"]`, `SUB_SCORE_LABELS`, `ANALYST_LEGEND_SECTIONS`.
  - `compute_dividend_safety_score(payout_ratio, dividend_rate, shares_outstanding, free_cashflow) -> float | None`
  - `compute_quality_score(profit_margin, operating_margins, revenue_growth, earnings_growth, debt_to_equity, current_ratio) -> float | None`
  - `compute_value_score(pe_ratio, forward_pe, price_to_book, price_local, target_mean_price, dividend_yield, five_year_avg_dividend_yield) -> float | None`
  - `compute_fit_score(position_weight_pct, sector_weight_pct) -> float | None`
  - `compute_add_score(dividend_safety, quality, value, fit) -> float | None`
  - `business_view(business_score) -> str`
  - `add_verdict(add_score) -> str`
  - `analyze_holding(holding, fundamentals, price_local, position_weight_pct, sector_weight_pct) -> dict` with keys `ticker, company, is_etf, dividend_safety, quality, value, fit, business_score, add_score, verdict, business_view, strongest, weakest` (`strongest`/`weakest` are `(label, score)` tuples or `None`).
  - `analyze_portfolio(holdings, latest_fundamentals, latest_history, allocation) -> list[dict]` — one `analyze_holding` dict per holding, in `holdings` order.
  - `rank_next_euro(analyses) -> list[dict]` — analyses with a numeric `add_score` sorted descending (ties by ticker), each gaining `rank` (1-based).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_analyst.py`:

```python
import pytest

from tools.analyst import (
    CONFIDENCE_LEVELS,
    VERDICT_ADD,
    VERDICT_HOLD,
    VERDICT_INSUFFICIENT,
    VERDICT_STOP,
    VERDICTS,
    VIEW_BEARISH,
    VIEW_BULLISH,
    VIEW_NEUTRAL,
    add_verdict,
    analyze_holding,
    business_view,
    compute_add_score,
    compute_dividend_safety_score,
    compute_fit_score,
    compute_quality_score,
    compute_value_score,
    rank_next_euro,
)

# A MDLZ-like profile: high yield, payout above the 75% line, dividend barely
# covered by free cash flow, heavy debt. Round numbers so the expected values
# below can be derived by hand.
PEP_LIKE_DIVIDEND = dict(payout_ratio=0.75, dividend_rate=6.0, shares_outstanding=1_000_000_000, free_cashflow=5_400_000_000)
HEALTHY_DIVIDEND = dict(payout_ratio=0.35, dividend_rate=2.0, shares_outstanding=1_000_000_000, free_cashflow=6_000_000_000)


def test_dividend_safety_penalises_high_payout_and_thin_cover():
    # payout component: 100 - (0.75-0.40)/0.60*100 = 41.667
    # cover = 5.4e9 / (6.0 * 1e9) = 0.90 -> (0.90-0.80)/(2.50-0.80)*100 = 5.882
    # mean -> 23.77
    assert compute_dividend_safety_score(**PEP_LIKE_DIVIDEND) == pytest.approx(23.77, abs=0.01)


def test_dividend_safety_full_marks_when_low_payout_and_well_covered():
    # payout 0.35 <= 0.40 -> 100; cover = 3.0 >= 2.5 -> 100
    assert compute_dividend_safety_score(**HEALTHY_DIVIDEND) == pytest.approx(100.0)


def test_dividend_safety_uses_whichever_component_is_available():
    only_payout = compute_dividend_safety_score(payout_ratio=0.75, dividend_rate=None, shares_outstanding=None, free_cashflow=None)
    assert only_payout == pytest.approx(41.667, abs=0.01)
    assert compute_dividend_safety_score(None, None, None, None) is None


def test_dividend_safety_zero_dividend_has_no_cover_component():
    # A non-payer: no dividend to cover, so only the payout component counts.
    assert compute_dividend_safety_score(0.0, 0.0, 1_000_000_000, 5_000_000_000) == pytest.approx(100.0)


def test_quality_blends_margins_growth_and_balance_sheet():
    # margins: min(0.20*500,100)=100 and min(0.25*400,100)=100 -> 100
    # growth: 50+0.05*500=75 and 50+0.10*100=60 -> 67.5
    # balance: 100-60/300*100=80 and 1.5/2*100=75 -> 77.5
    # mean -> 81.667
    score = compute_quality_score(
        profit_margin=0.20, operating_margins=0.25, revenue_growth=0.05,
        earnings_growth=0.10, debt_to_equity=60.0, current_ratio=1.5,
    )
    assert score == pytest.approx(81.667, abs=0.01)


def test_quality_clamps_extremes_and_returns_none_without_inputs():
    crushed = compute_quality_score(
        profit_margin=-0.5, operating_margins=-0.5, revenue_growth=-0.9,
        earnings_growth=-5.0, debt_to_equity=900.0, current_ratio=0.1,
    )
    # margins 0, growth 0, balance = (0 + 0.1/2*100)/2 = 2.5 -> mean = 0.833
    assert crushed == pytest.approx(0.833, abs=0.01)
    assert compute_quality_score(None, None, None, None, None, None) is None


def test_value_blends_four_components():
    # fwd P/E: 50 + (20-16)/20*100 = 70
    # P/B 2.8: 100 - (2.8-1)/9*100 = 80
    # target: 50 + (120/100 - 1)*100 = 70
    # yield vs 5y avg: 50 + (4.0/3.2 - 1)*100 = 75
    score = compute_value_score(
        pe_ratio=20.0, forward_pe=16.0, price_to_book=2.8, price_local=100.0,
        target_mean_price=120.0, dividend_yield=4.0, five_year_avg_dividend_yield=3.2,
    )
    assert score == pytest.approx(73.75, abs=0.01)
    assert compute_value_score(None, None, None, None, None, None, None) is None


def test_fit_penalises_concentration():
    assert compute_fit_score(5.0, 15.0) == pytest.approx(100.0)
    # position 10% -> 50; sector 25% -> 100-(25-15)/15*100 = 33.333; mean 41.667
    assert compute_fit_score(10.0, 25.0) == pytest.approx(41.667, abs=0.01)
    # A mid-sized position in a sector just above the 25% cap
    assert compute_fit_score(6.0, 27.0) == pytest.approx(55.0, abs=0.01)
    assert compute_fit_score(20.0, 40.0) == pytest.approx(0.0)


def test_add_score_weights_and_renormalises():
    # .30*23.77 + .30*81.667 + .25*73.75 + .15*41.667 = 56.32
    assert compute_add_score(23.77, 81.667, 73.75, 41.667) == pytest.approx(56.32, abs=0.01)
    # fit missing -> weights renormalise over 0.85
    expected = (0.30 * 40 + 0.30 * 60 + 0.25 * 80) / 0.85
    assert compute_add_score(40.0, 60.0, 80.0, None) == pytest.approx(expected, abs=0.01)
    assert compute_add_score(None, None, None, None) is None


def test_verdict_and_view_band_boundaries():
    assert add_verdict(65.0) == VERDICT_ADD
    assert add_verdict(64.99) == VERDICT_HOLD
    assert add_verdict(45.0) == VERDICT_HOLD
    assert add_verdict(44.99) == VERDICT_STOP
    assert add_verdict(None) == VERDICT_INSUFFICIENT
    assert business_view(60.0) == VIEW_BULLISH
    assert business_view(59.99) == VIEW_NEUTRAL
    assert business_view(40.0) == VIEW_NEUTRAL
    assert business_view(39.99) == VIEW_BEARISH
    assert business_view(None) == VERDICT_INSUFFICIENT


def test_no_verdict_is_ever_sell():
    assert "Sell" not in VERDICTS
    assert CONFIDENCE_LEVELS == ["high", "medium", "low"]


def _fundamentals(**overrides):
    base = dict(
        payout_ratio=0.75, dividend_rate=6.0, shares_outstanding=1_000_000_000, free_cashflow=5_400_000_000,
        profit_margin=0.20, operating_margins=0.25, revenue_growth=0.05, earnings_growth=0.10,
        debt_to_equity=60.0, current_ratio=1.5,
        pe_ratio=20.0, forward_pe=16.0, price_to_book=2.8, target_mean_price=120.0,
        dividend_yield=4.0, five_year_avg_dividend_yield=3.2,
    )
    base.update(overrides)
    return base


def test_analyze_holding_full_profile():
    holding = {"ticker": "MDLZ", "company": "Mondelez International", "is_etf": False}

    result = analyze_holding(holding, _fundamentals(), price_local=100.0, position_weight_pct=10.0, sector_weight_pct=25.0)

    assert result["ticker"] == "MDLZ"
    assert result["dividend_safety"] == pytest.approx(23.77, abs=0.01)
    assert result["quality"] == pytest.approx(81.667, abs=0.01)
    assert result["value"] == pytest.approx(73.75, abs=0.01)
    assert result["fit"] == pytest.approx(41.667, abs=0.01)
    assert result["add_score"] == pytest.approx(56.32, abs=0.01)
    # business score excludes fit: (23.77+81.667+73.75)/3 = 59.73 -> just under Bullish
    assert result["business_score"] == pytest.approx(59.73, abs=0.01)
    assert result["business_view"] == VIEW_NEUTRAL
    assert result["verdict"] == VERDICT_HOLD
    assert result["strongest"][0] == "Quality"
    assert result["weakest"][0] == "Dividend safety"


def test_analyze_holding_etf_scores_on_value_and_fit_only():
    holding = {"ticker": "VWRL.AS", "company": "Vanguard FTSE All-World", "is_etf": True}

    result = analyze_holding(holding, {"pe_ratio": 20.0, "forward_pe": 16.0}, price_local=100.0,
                             position_weight_pct=14.3, sector_weight_pct=14.3)

    assert result["is_etf"] is True
    assert result["dividend_safety"] is None and result["quality"] is None
    assert result["value"] == pytest.approx(70.0, abs=0.01)  # only the forward-P/E component exists
    assert result["business_view"] == VERDICT_INSUFFICIENT  # no business sub-scores to judge
    assert result["verdict"] in (VERDICT_ADD, VERDICT_HOLD, VERDICT_STOP)  # still ranked


def test_analyze_holding_non_etf_missing_data_is_insufficient():
    holding = {"ticker": "XYZ", "company": "Unknown Co", "is_etf": False}

    result = analyze_holding(holding, {"pe_ratio": 20.0, "forward_pe": 16.0}, price_local=100.0,
                             position_weight_pct=1.0, sector_weight_pct=5.0)

    # only 1 of 3 business sub-scores available and not an ETF
    assert result["verdict"] == VERDICT_INSUFFICIENT
    assert result["business_view"] == VERDICT_INSUFFICIENT
    assert result["add_score"] is None


def test_rank_next_euro_orders_and_excludes_insufficient():
    analyses = [
        {"ticker": "AAA", "add_score": 50.0, "verdict": VERDICT_HOLD},
        {"ticker": "BBB", "add_score": 80.0, "verdict": VERDICT_ADD},
        {"ticker": "CCC", "add_score": None, "verdict": VERDICT_INSUFFICIENT},
        {"ticker": "DDD", "add_score": 50.0, "verdict": VERDICT_HOLD},
    ]

    ranked = rank_next_euro(analyses)

    assert [r["ticker"] for r in ranked] == ["BBB", "AAA", "DDD"]  # ties broken by ticker
    assert [r["rank"] for r in ranked] == [1, 2, 3]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_analyst.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'tools.analyst'`.

- [ ] **Step 3: Write the implementation**

Create `tools/analyst.py`:

```python
"""Strategy-tuned scoring for the owner's long-term dividend portfolio.

Answers two questions per holding: is the BUSINESS attractive right now
(Bullish/Neutral/Bearish), and should NEW money go here (Add/Hold/Stop
adding). They are deliberately separate — a fine company he is already
overweight in should score well on the first and badly on the second.

There is no "sell" verdict: the owner holds long term, so the worst any
holding gets is "no new money here". Pure functions, no I/O."""

VERDICT_ADD = "Add"
VERDICT_HOLD = "Hold"
VERDICT_STOP = "Stop adding"
VERDICT_INSUFFICIENT = "Insufficient data"
VERDICTS = [VERDICT_ADD, VERDICT_HOLD, VERDICT_STOP, VERDICT_INSUFFICIENT]

VIEW_BULLISH = "Bullish"
VIEW_NEUTRAL = "Neutral"
VIEW_BEARISH = "Bearish"
BUSINESS_VIEWS = [VIEW_BULLISH, VIEW_NEUTRAL, VIEW_BEARISH, VERDICT_INSUFFICIENT]

CONFIDENCE_LEVELS = ["high", "medium", "low"]

# Dividend safety is weighted highest because the owner reinvests every dividend:
# a cut doesn't just cost income, it breaks the compounding the plan rests on.
WEIGHTS = {"dividend_safety": 0.30, "quality": 0.30, "value": 0.25, "fit": 0.15}

SUB_SCORE_LABELS = {
    "dividend_safety": "Dividend safety",
    "quality": "Quality",
    "value": "Valuation",
    "fit": "Portfolio fit",
}

ADD_BAND = 65.0
HOLD_BAND = 45.0
BULLISH_BAND = 60.0
NEUTRAL_BAND = 40.0


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(present) / len(present)


def _linear(value: float, best: float, worst: float) -> float:
    """100 at `best`, 0 at `worst`, linear between, clamped outside."""
    if best == worst:
        return 50.0
    return _clamp((value - worst) / (best - worst) * 100)


def compute_dividend_safety_score(payout_ratio, dividend_rate, shares_outstanding, free_cashflow) -> float | None:
    """Can the dividend survive? Payout ratio plus free-cash-flow cover.
    A payout above 0.75 is penalised hard per the owner's rule."""
    components: list[float | None] = []

    if payout_ratio is not None:
        components.append(_linear(payout_ratio, best=0.40, worst=1.00))

    if dividend_rate and shares_outstanding and free_cashflow is not None:
        total_dividend = dividend_rate * shares_outstanding
        if total_dividend > 0:
            components.append(_linear(free_cashflow / total_dividend, best=2.5, worst=0.8))

    return _mean(components)


def compute_quality_score(profit_margin, operating_margins, revenue_growth, earnings_growth, debt_to_equity, current_ratio) -> float | None:
    """Is this a good business? Margins, growth, and balance-sheet strength,
    each contributing equally when available."""
    margins = _mean([
        _clamp(profit_margin * 500) if profit_margin is not None else None,
        _clamp(operating_margins * 400) if operating_margins is not None else None,
    ])
    growth = _mean([
        _clamp(50 + revenue_growth * 500) if revenue_growth is not None else None,
        # Earnings growth is far noisier quarter to quarter, so it moves the
        # score less per unit than revenue growth does.
        _clamp(50 + earnings_growth * 100) if earnings_growth is not None else None,
    ])
    balance = _mean([
        _clamp(100 - debt_to_equity / 300 * 100) if debt_to_equity is not None else None,
        _clamp(current_ratio / 2 * 100) if current_ratio is not None else None,
    ])
    return _mean([margins, growth, balance])


def compute_value_score(pe_ratio, forward_pe, price_to_book, price_local, target_mean_price, dividend_yield, five_year_avg_dividend_yield) -> float | None:
    """Is it cheap? Four independent cheapness tests, averaged."""
    components: list[float | None] = []

    if pe_ratio and forward_pe and pe_ratio > 0:
        components.append(_clamp(50 + (pe_ratio - forward_pe) / pe_ratio * 100))

    if price_to_book is not None:
        components.append(_linear(price_to_book, best=1.0, worst=10.0))

    if target_mean_price and price_local:
        components.append(_clamp(50 + (target_mean_price / price_local - 1) * 100))

    if dividend_yield and five_year_avg_dividend_yield:
        # The dividend investor's cheapness test: yielding more than its own
        # history usually means the price fell faster than the dividend.
        components.append(_clamp(50 + (dividend_yield / five_year_avg_dividend_yield - 1) * 100))

    return _mean(components)


def compute_fit_score(position_weight_pct, sector_weight_pct) -> float | None:
    """Scores the owner's PORTFOLIO, not the company: how much room is left for
    more of this. Falls to 0 at a 15% position or a 30% sector."""
    components: list[float | None] = []
    if position_weight_pct is not None:
        components.append(_linear(position_weight_pct, best=5.0, worst=15.0))
    if sector_weight_pct is not None:
        components.append(_linear(sector_weight_pct, best=15.0, worst=30.0))
    return _mean(components)


def compute_add_score(dividend_safety, quality, value, fit) -> float | None:
    """Weighted mean of whichever sub-scores exist, renormalised over the
    weights actually used so a missing component doesn't drag the result down."""
    pairs = [
        (dividend_safety, WEIGHTS["dividend_safety"]),
        (quality, WEIGHTS["quality"]),
        (value, WEIGHTS["value"]),
        (fit, WEIGHTS["fit"]),
    ]
    present = [(score, weight) for score, weight in pairs if score is not None]
    if not present:
        return None
    total_weight = sum(weight for _score, weight in present)
    return sum(score * weight for score, weight in present) / total_weight


def add_verdict(add_score: float | None) -> str:
    if add_score is None:
        return VERDICT_INSUFFICIENT
    if add_score >= ADD_BAND:
        return VERDICT_ADD
    if add_score >= HOLD_BAND:
        return VERDICT_HOLD
    return VERDICT_STOP


def business_view(business_score: float | None) -> str:
    if business_score is None:
        return VERDICT_INSUFFICIENT
    if business_score >= BULLISH_BAND:
        return VIEW_BULLISH
    if business_score >= NEUTRAL_BAND:
        return VIEW_NEUTRAL
    return VIEW_BEARISH


def analyze_holding(holding: dict, fundamentals: dict, price_local, position_weight_pct, sector_weight_pct) -> dict:
    """One holding's four sub-scores, composite scores and both verdicts."""
    f = fundamentals or {}
    is_etf = bool(holding.get("is_etf"))

    # An ETF has no payout ratio, margins or debt of its own — those sub-scores
    # are not "missing data", they simply don't apply, so it is scored on
    # valuation and fit alone rather than being dropped from the ranking.
    dividend_safety = None if is_etf else compute_dividend_safety_score(
        f.get("payout_ratio"), f.get("dividend_rate"), f.get("shares_outstanding"), f.get("free_cashflow"),
    )
    quality = None if is_etf else compute_quality_score(
        f.get("profit_margin"), f.get("operating_margins"), f.get("revenue_growth"),
        f.get("earnings_growth"), f.get("debt_to_equity"), f.get("current_ratio"),
    )
    value = compute_value_score(
        f.get("pe_ratio"), f.get("forward_pe"), f.get("price_to_book"), price_local,
        f.get("target_mean_price"), f.get("dividend_yield"), f.get("five_year_avg_dividend_yield"),
    )
    fit = compute_fit_score(position_weight_pct, sector_weight_pct)

    business_score = _mean([dividend_safety, quality, value])
    business_parts = [s for s in (dividend_safety, quality, value) if s is not None]

    if not is_etf and len(business_parts) < 2:
        # Too little to judge a company on — say so instead of guessing.
        add_score = None
        verdict = VERDICT_INSUFFICIENT
        view = VERDICT_INSUFFICIENT
    else:
        add_score = compute_add_score(dividend_safety, quality, value, fit)
        verdict = add_verdict(add_score)
        view = VERDICT_INSUFFICIENT if is_etf else business_view(business_score)

    scored = {
        SUB_SCORE_LABELS[key]: score
        for key, score in (
            ("dividend_safety", dividend_safety), ("quality", quality), ("value", value), ("fit", fit),
        )
        if score is not None
    }
    strongest = max(scored.items(), key=lambda kv: kv[1]) if scored else None
    weakest = min(scored.items(), key=lambda kv: kv[1]) if scored else None

    return {
        "ticker": holding["ticker"],
        "company": holding["company"],
        "is_etf": is_etf,
        "dividend_safety": dividend_safety,
        "quality": quality,
        "value": value,
        "fit": fit,
        "business_score": business_score,
        "add_score": add_score,
        "verdict": verdict,
        "business_view": view,
        "strongest": strongest,
        "weakest": weakest,
    }


def analyze_portfolio(holdings: list[dict], latest_fundamentals: dict, latest_history: dict, allocation: dict) -> list[dict]:
    """Runs analyze_holding for every holding, pulling each one's position and
    sector weights out of the allocation breakdown."""
    position_weight = {p["ticker"]: p["weight_pct"] for p in allocation.get("positions", [])}
    sector_of = {p["ticker"]: p.get("sector") for p in allocation.get("positions", [])}
    sector_weight = {s["name"]: s["weight_pct"] for s in allocation.get("sectors", [])}

    analyses = []
    for h in holdings:
        ticker = h["ticker"]
        hist = latest_history.get(ticker, {})
        price_local = hist.get("price_local")
        price_local = float(price_local) if price_local not in (None, "") else None
        analyses.append(
            analyze_holding(
                h,
                latest_fundamentals.get(ticker, {}),
                price_local,
                position_weight.get(ticker),
                sector_weight.get(sector_of.get(ticker)),
            )
        )
    return analyses


def rank_next_euro(analyses: list[dict]) -> list[dict]:
    """Where the next contribution should go: every rankable holding by
    add_score, best first. Holdings without enough data are left out rather
    than ranked last on a guessed score."""
    rankable = [a for a in analyses if a.get("add_score") is not None]
    rankable.sort(key=lambda a: (-a["add_score"], a["ticker"]))
    return [{**a, "rank": i} for i, a in enumerate(rankable, start=1)]


ANALYST_LEGEND_SECTIONS = [
    (
        "Verdict (Add / Hold / Stop adding)",
        "Where new money should go, not whether to own the stock. \"Add\" = "
        "this is among the better places for the next contribution. \"Hold\" "
        "= fine to own, nothing compelling right now. \"Stop adding\" = no "
        "new money here for now. There is deliberately no \"sell\" verdict - "
        "the strategy is long-term holding, so the worst case is pausing "
        "contributions, never exiting.",
    ),
    (
        "Business view (Bullish / Neutral / Bearish)",
        "A judgment on the COMPANY, separate from the Add decision, and based "
        "on dividend safety, quality and valuation only - portfolio "
        "concentration is excluded. This is why a good company can read "
        "Bullish and \"Stop adding\" at the same time: nothing is wrong with "
        "it, there is simply already too much of it in the portfolio.",
    ),
    (
        "The four sub-scores",
        "Dividend safety (0-100): payout ratio and whether free cash flow "
        "covers the dividend - weighted heaviest, because a cut breaks the "
        "reinvestment plan. Quality: margins, growth and balance sheet. "
        "Valuation: forward P/E, price-to-book, analyst target and yield "
        "versus the company's own 5-year average. Portfolio fit: how much "
        "room is left before the position (>10%) or its sector (>25%) is "
        "overweight.",
    ),
    (
        "Confidence",
        "How much weight to put on the verdict: high, medium or low. Low "
        "confidence always names what is missing or unresolved. A verdict "
        "that disagrees with the computed score carries a stated reason for "
        "the override - so a disagreement is always visible, never silent.",
    ),
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_analyst.py -v` then `python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/analyst.py tests/test_analyst.py
git commit -m "feat: add analyst scoring engine with Add/Hold/Stop verdicts

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Judgment fields and the override guardrail

**Files:**
- Modify: `tools/append_analysis.py` (`build_entry` and `main`)
- Test: `tests/test_append_analysis.py`

**Interfaces:**
- Consumes (Task 2): `VERDICTS`, `BUSINESS_VIEWS`, `CONFIDENCE_LEVELS` from `tools.analyst`.
- Produces: `build_entry(...)` gains keyword-only params `verdict=None, business_view=None, confidence=None, case_for=None, case_against=None, what_would_change_my_mind=None, override_reason=None, computed_verdict=None`, storing each in the entry dict under the same names (omitting keys that are `None`). New CLI flags `--verdict --business-view --confidence --case-for --case-against --what-would-change-my-mind --override-reason --computed-verdict`. The existing 6 positional params and their flags are unchanged, and all new flags are optional, so existing calls keep working.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_append_analysis.py` (check the file's existing imports first):

```python
import pytest

from tools.analyst import VERDICT_ADD, VERDICT_HOLD, VIEW_BULLISH
from tools.append_analysis import build_entry


def _base_kwargs():
    return dict(
        price_change_pct=1.0, window="1d", price_narrative="n", status="s", watch="w",
        news_sentiment_score=50, today_str="2026-09-21",
    )


def test_build_entry_stores_judgment_fields():
    entry = build_entry(
        **_base_kwargs(),
        verdict=VERDICT_HOLD, business_view=VIEW_BULLISH, confidence="medium",
        case_for="Yield 4.4% vs 3.0% 5y average", case_against="Payout ratio 0.75",
        what_would_change_my_mind="Revenue growth back above 3% for two quarters",
        computed_verdict=VERDICT_HOLD,
    )

    assert entry["verdict"] == VERDICT_HOLD
    assert entry["business_view"] == VIEW_BULLISH
    assert entry["confidence"] == "medium"
    assert entry["case_for"].startswith("Yield")
    assert entry["what_would_change_my_mind"].startswith("Revenue growth")
    assert "override_reason" not in entry  # nothing was overridden


def test_build_entry_without_judgment_fields_is_unchanged():
    entry = build_entry(**_base_kwargs())

    assert entry["news_sentiment_score"] == 50
    for key in ("verdict", "business_view", "confidence", "case_for", "override_reason"):
        assert key not in entry


def test_build_entry_rejects_verdict_outside_the_ladder():
    with pytest.raises(ValueError, match="verdict"):
        build_entry(**_base_kwargs(), verdict="Sell", computed_verdict=VERDICT_HOLD)


def test_build_entry_rejects_unknown_confidence():
    with pytest.raises(ValueError, match="confidence"):
        build_entry(**_base_kwargs(), verdict=VERDICT_HOLD, confidence="pretty sure", computed_verdict=VERDICT_HOLD)


def test_build_entry_requires_reason_when_overriding_the_computed_verdict():
    with pytest.raises(ValueError, match="override_reason"):
        build_entry(**_base_kwargs(), verdict=VERDICT_ADD, computed_verdict=VERDICT_HOLD)


def test_build_entry_accepts_override_with_a_reason():
    entry = build_entry(
        **_base_kwargs(), verdict=VERDICT_ADD, computed_verdict=VERDICT_HOLD,
        override_reason="Score penalises the sector weight twice; the position itself is only 6%",
    )

    assert entry["verdict"] == VERDICT_ADD
    assert entry["computed_verdict"] == VERDICT_HOLD
    assert entry["override_reason"].startswith("Score penalises")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_append_analysis.py -v`
Expected: FAIL — `TypeError: build_entry() got an unexpected keyword argument 'verdict'`.

- [ ] **Step 3: Implement**

In `tools/append_analysis.py`, add the import at the top:

```python
from tools.analyst import BUSINESS_VIEWS, CONFIDENCE_LEVELS, VERDICTS
```

Replace `build_entry`'s signature and body with:

```python
def build_entry(
    price_change_pct: float,
    window: str,
    price_narrative: str,
    status: str,
    watch: str,
    news_sentiment_score: int,
    today_str: str | None = None,
    *,
    verdict: str | None = None,
    business_view: str | None = None,
    confidence: str | None = None,
    case_for: str | None = None,
    case_against: str | None = None,
    what_would_change_my_mind: str | None = None,
    override_reason: str | None = None,
    computed_verdict: str | None = None,
) -> dict:
    """news_sentiment_score is the agent's own 0-100 judgment of how the
    week's fetched headlines skew (50 = neutral/no clear skew), unlike the
    other three scores which are computed deterministically from fetched
    data in tools.scoring.

    The judgment fields are the agent's analyst opinion (see
    tools/analyst.py for the computed side). `verdict` must come from the
    Add/Hold/Stop adding ladder — there is no "sell" verdict. If the agent's
    verdict differs from `computed_verdict`, an `override_reason` is
    REQUIRED: disagreeing with the score is allowed, doing it silently is
    not, so every override stays visible in the holding's history."""
    if not 0 <= news_sentiment_score <= 100:
        raise ValueError(f"news_sentiment_score must be 0-100, got {news_sentiment_score}")
    if verdict is not None and verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}, got {verdict!r}")
    if business_view is not None and business_view not in BUSINESS_VIEWS:
        raise ValueError(f"business_view must be one of {BUSINESS_VIEWS}, got {business_view!r}")
    if confidence is not None and confidence not in CONFIDENCE_LEVELS:
        raise ValueError(f"confidence must be one of {CONFIDENCE_LEVELS}, got {confidence!r}")
    if verdict is not None and computed_verdict is not None and verdict != computed_verdict and not override_reason:
        raise ValueError(
            f"verdict {verdict!r} differs from the computed verdict {computed_verdict!r} — "
            "pass --override-reason explaining why the score is wrong here"
        )

    entry = {
        "date": today_str or date.today().isoformat(),
        "price_change_pct": price_change_pct,
        "window": window,
        "price_narrative": price_narrative,
        "status": status,
        "watch": watch,
        "news_sentiment_score": news_sentiment_score,
    }
    optional = {
        "verdict": verdict,
        "business_view": business_view,
        "confidence": confidence,
        "case_for": case_for,
        "case_against": case_against,
        "what_would_change_my_mind": what_would_change_my_mind,
        "computed_verdict": computed_verdict,
        "override_reason": override_reason,
    }
    entry.update({k: v for k, v in optional.items() if v is not None})
    return entry
```

Then in `main()`, add the new arguments after `--news-sentiment-score` and pass them through:

```python
    parser.add_argument("--verdict", choices=VERDICTS)
    parser.add_argument("--business-view", choices=BUSINESS_VIEWS)
    parser.add_argument("--confidence", choices=CONFIDENCE_LEVELS)
    parser.add_argument("--case-for")
    parser.add_argument("--case-against")
    parser.add_argument("--what-would-change-my-mind")
    parser.add_argument("--override-reason")
    parser.add_argument("--computed-verdict", choices=VERDICTS,
                        help="the verdict tools.analyst computed; supplying it enables the override guardrail")
    args = parser.parse_args()

    entry = build_entry(
        args.price_change_pct, args.window, args.price_narrative, args.status, args.watch,
        args.news_sentiment_score,
        verdict=args.verdict, business_view=args.business_view, confidence=args.confidence,
        case_for=args.case_for, case_against=args.case_against,
        what_would_change_my_mind=args.what_would_change_my_mind,
        override_reason=args.override_reason, computed_verdict=args.computed_verdict,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_append_analysis.py -v` then `python -m pytest -q`
Expected: all PASS. Also check the CLI rejects a bad verdict:
`python -m tools.append_analysis --ticker TEST --price-change-pct 0 --window w --price-narrative n --status s --watch w --news-sentiment-score 50 --verdict Sell`
Expected: argparse error listing the valid choices, exit code 2, nothing written.

- [ ] **Step 5: Commit**

```bash
git add tools/append_analysis.py tests/test_append_analysis.py
git commit -m "feat: record analyst verdicts with an override guardrail

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Sheet — Verdict/Confidence columns, Analyst tab, legend

**Files:**
- Modify: `tools/sync_google_sheet.py`
- Test: `tests/test_sync_google_sheet.py`

**Interfaces:**
- Consumes (Tasks 2-3): `analyze_portfolio`, `rank_next_euro`, `ANALYST_LEGEND_SECTIONS`, `SUB_SCORE_LABELS`, `VERDICT_ADD`, `VERDICT_STOP` from `tools.analyst`; the analysis-entry keys `verdict`, `confidence` written by Task 3.
- Produces: `OVERVIEW_HEADER` gains `"Verdict"`, `"Confidence"` directly after `"Konkorde"` and before `"P/E"`; `ANALYST_TAB_NAME = "Analyst"`; `build_analyst_rows(ranked, analyses) -> list[list]`; `write_analyst_tab(spreadsheet, rows)`; `build_overview_rows(...)` gains a trailing optional param `latest_verdicts: dict[str, dict] | None = None` where each value is `{"verdict": str, "confidence": str}`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sync_google_sheet.py`:

```python
def test_overview_header_has_verdict_columns_before_pe():
    i = OVERVIEW_HEADER.index("Verdict")
    assert OVERVIEW_HEADER[i - 1] == "Konkorde"
    assert OVERVIEW_HEADER[i:i + 3] == ["Verdict", "Confidence", "P/E"]


def test_build_overview_rows_includes_verdict_and_confidence():
    from tools.analyst import VERDICT_STOP

    holding = {"ticker": "MDLZ", "company": "Mondelez", "shares": 10, "currency": "USD", "avg_cost_local": 150.00, "is_etf": False}
    history = {"MDLZ": {"price_local": "129.75", "value_eur": "2000", "gp_eur": "-400", "gp_pct": "-19.2", "date": "2026-09-21"}}
    verdicts = {"MDLZ": {"verdict": VERDICT_STOP, "confidence": "medium"}}

    rows = build_overview_rows([holding], history, {}, {}, None, verdicts)

    row = dict(zip(OVERVIEW_HEADER, rows[1]))
    assert row["Verdict"] == VERDICT_STOP
    assert row["Confidence"] == "medium"


def test_build_overview_rows_verdict_blank_when_missing():
    holding = {"ticker": "MDLZ", "company": "Mondelez", "shares": 10, "currency": "USD", "avg_cost_local": 150.00, "is_etf": False}
    history = {"MDLZ": {"price_local": "129.75", "value_eur": "2000", "gp_eur": "-400", "gp_pct": "-19.2", "date": "2026-09-21"}}

    rows = build_overview_rows([holding], history, {}, {})

    row = dict(zip(OVERVIEW_HEADER, rows[1]))
    assert row["Verdict"] == "" and row["Confidence"] == ""


def test_build_analyst_rows_ranks_and_lists_unrankable():
    from tools.analyst import VERDICT_ADD, VERDICT_INSUFFICIENT

    analyses = [
        {"ticker": "BAC", "company": "Bank of America", "add_score": 72.0, "verdict": VERDICT_ADD,
         "business_view": "Bullish", "dividend_safety": 80.0, "quality": 70.0, "value": 65.0, "fit": 50.0,
         "strongest": ("Dividend safety", 80.0), "weakest": ("Portfolio fit", 50.0)},
        {"ticker": "XYZ", "company": "Unknown", "add_score": None, "verdict": VERDICT_INSUFFICIENT,
         "business_view": VERDICT_INSUFFICIENT, "dividend_safety": None, "quality": None, "value": None,
         "fit": None, "strongest": None, "weakest": None},
    ]
    ranked = [{**analyses[0], "rank": 1}]

    rows = build_analyst_rows(ranked, analyses)

    assert rows[0][0] == "Rank"
    assert rows[1][:3] == [1, "BAC", "Bank of America"]
    assert rows[1][3] == VERDICT_ADD
    flat = [str(cell) for row in rows for cell in row]
    assert any("XYZ" in cell for cell in flat)  # unrankable holdings still reported
    assert any("Insufficient data" in cell for cell in flat)


def test_analyst_legend_rows_are_included():
    from tools.analyst import ANALYST_LEGEND_SECTIONS

    terms = [row[0] for row in build_legend_rows()[1:]]
    for term, _explanation in ANALYST_LEGEND_SECTIONS:
        assert term in terms


def test_verdict_format_requests_colour_add_green_stop_red():
    from tools.analyst import VERDICT_ADD, VERDICT_STOP
    from tools.scoring import DELTA_DOWN_COLOR, DELTA_UP_COLOR
    from tools.ticker_tab import hex_to_rgb_fraction

    requests = _signal_text_format_requests(sheet_id=3, col_index=5, row_count=10,
                                            positive_prefix=VERDICT_ADD, negative_prefix=VERDICT_STOP)
    rules = [r["addConditionalFormatRule"]["rule"]["booleanRule"] for r in requests]
    by_value = {b["condition"]["values"][0]["userEnteredValue"]: b["format"] for b in rules}

    assert by_value[VERDICT_ADD]["textFormat"]["foregroundColor"] == hex_to_rgb_fraction(DELTA_UP_COLOR)
    assert by_value[VERDICT_STOP]["textFormat"]["foregroundColor"] == hex_to_rgb_fraction(DELTA_DOWN_COLOR)
```

Also update `test_build_legend_rows_covers_every_documented_term` to expect `LEGEND_SECTIONS + TECHNICAL_LEGEND_SECTIONS + ANALYST_LEGEND_SECTIONS`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sync_google_sheet.py -v`
Expected: FAIL — `ValueError: 'Verdict' is not in list` / `NameError: build_analyst_rows`.

- [ ] **Step 3: Implement**

3a. Imports — add:

```python
from tools.analyst import (
    ANALYST_LEGEND_SECTIONS,
    VERDICT_ADD,
    VERDICT_STOP,
    analyze_portfolio,
    rank_next_euro,
)
```

3b. Header — replace the `OVERVIEW_HEADER += ["P/E", "Div Yield", "Last Updated"]` line with:

```python
OVERVIEW_HEADER += ["Verdict", "Confidence"]
OVERVIEW_HEADER += ["P/E", "Div Yield", "Last Updated"]
```

and add `ANALYST_TAB_NAME = "Analyst"` next to the other tab-name constants.

3c. `build_overview_rows` — add a trailing parameter `latest_verdicts: dict[str, dict] | None = None`, and insert before the `row += [fund.get("pe_ratio", ...)]` line:

```python
        judgment = (latest_verdicts or {}).get(h["ticker"], {})
        row += [judgment.get("verdict", ""), judgment.get("confidence", "")]
```

3d. `build_legend_rows` — iterate `LEGEND_SECTIONS + TECHNICAL_LEGEND_SECTIONS + ANALYST_LEGEND_SECTIONS`.

3e. `apply_overview_formatting` — add before `if requests:`:

```python
    requests += _signal_text_format_requests(
        sheet_id, OVERVIEW_HEADER.index("Verdict"), row_count, VERDICT_ADD, VERDICT_STOP
    )
```

3f. New functions, after `build_allocation_rows`:

```python
ANALYST_HEADER = ["Rank", "Ticker", "Company", "Verdict", "Business view", "Add score",
                  "Dividend safety", "Quality", "Valuation", "Portfolio fit", "Strongest", "Weakest"]


def _score_cell(value) -> float | str:
    return "" if value is None else round(value, 1)


def build_analyst_rows(ranked: list[dict], analyses: list[dict]) -> list[list]:
    """The Analyst tab: every holding ranked by where the next contribution
    should go, then any holding that couldn't be scored, listed below rather
    than ranked on a guess."""
    rows = [ANALYST_HEADER]
    for a in ranked:
        rows.append([
            a["rank"], a["ticker"], a["company"], a["verdict"], a["business_view"],
            _score_cell(a["add_score"]), _score_cell(a["dividend_safety"]), _score_cell(a["quality"]),
            _score_cell(a["value"]), _score_cell(a["fit"]),
            f"{a['strongest'][0]} ({round(a['strongest'][1])})" if a.get("strongest") else "",
            f"{a['weakest'][0]} ({round(a['weakest'][1])})" if a.get("weakest") else "",
        ])

    unrankable = [a for a in analyses if a.get("add_score") is None]
    if unrankable:
        rows.append([""])
        rows.append(["Not ranked - insufficient data"])
        for a in unrankable:
            rows.append(["", a["ticker"], a["company"], a["verdict"]])
    return rows


def write_analyst_tab(spreadsheet, rows: list[list]) -> None:
    width = max(len(r) for r in rows)
    existing_titles = {ws.title for ws in spreadsheet.worksheets()}
    if ANALYST_TAB_NAME in existing_titles:
        ws = spreadsheet.worksheet(ANALYST_TAB_NAME)
        ws.clear()
        ws.resize(rows=max(len(rows), ws.row_count), cols=max(width, ws.col_count))
    else:
        ws = spreadsheet.add_worksheet(title=ANALYST_TAB_NAME, rows=max(len(rows), 50), cols=width, index=2)
    if ws.index != 2:
        ws.update_index(2)  # after Legend and Allocation, before Overview
    ws.update(rows)
    ws.format("A1:L1", {"textFormat": {"bold": True}})
```

3g. `write_sheet` — add an `analyst_rows` parameter after `allocation`, and call `write_analyst_tab(spreadsheet, analyst_rows)` right after `write_allocation_tab(...)`.

3h. `main()` — after `allocation = compute_allocation(...)` (move that call above the sheet write if needed), add:

```python
    analyses = analyze_portfolio(holdings, latest_fundamentals, latest_history, allocation)
    ranked = rank_next_euro(analyses)
    latest_verdicts = {
        t: {"verdict": a.get("verdict", ""), "confidence": a.get("confidence", "")}
        for t, a in latest_analysis.items()
    }
```

and pass `latest_verdicts` as the last argument to `build_overview_rows`, and `build_analyst_rows(ranked, analyses)` to `write_sheet`.

Note: the Overview Verdict/Confidence columns come from the agent's recorded analysis entries (`latest_analysis`), NOT from the computed scores — the agent's verdict is the one the owner reads, and it may be an override. The Analyst tab shows the computed scores.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q` and `python -c "import tools.sync_google_sheet"`
Expected: all PASS, clean import.

- [ ] **Step 5: Commit**

```bash
git add tools/sync_google_sheet.py tests/test_sync_google_sheet.py
git commit -m "feat: analyst verdict columns and Analyst tab in the Sheet

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Doc — Analyst View page and next-euro ranking

**Files:**
- Modify: `tools/sync_summary_doc.py`
- Test: `tests/test_sync_summary_doc.py`

**Interfaces:**
- Consumes (Tasks 2-3): `analyze_portfolio`, `rank_next_euro` from `tools.analyst`; analysis-entry keys `verdict`, `business_view`, `confidence`, `case_for`, `case_against`, `what_would_change_my_mind`, `override_reason`.
- Produces: `render_analyst_text(analyses, latest_analysis) -> tuple[str, tuple[int, int], list[tuple[int, int]], list[tuple[int, int, str]]]` returning `(text, title_range, bold_ranges, colored_ranges)`; `render_next_euro_text(ranked) -> tuple[str, tuple[int, int], list[tuple[int, int]]]` returning `(text, title_range, bold_ranges)`; both wired into `write_doc`'s `front_pages` list after the Top Picks page.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sync_summary_doc.py`:

```python
def test_render_analyst_text_shows_verdict_case_and_override():
    from tools.analyst import VERDICT_ADD, VERDICT_HOLD
    from tools.sync_summary_doc import render_analyst_text

    analyses = [{
        "ticker": "MDLZ", "company": "Mondelez", "is_etf": False, "verdict": VERDICT_HOLD,
        "business_view": "Neutral", "add_score": 56.3, "business_score": 59.7,
        "dividend_safety": 23.8, "quality": 81.7, "value": 73.8, "fit": 41.7,
        "strongest": ("Quality", 81.7), "weakest": ("Dividend safety", 23.8),
    }]
    latest_analysis = {"MDLZ": {
        "verdict": VERDICT_ADD, "business_view": "Neutral", "confidence": "low",
        "case_for": "Yield 4.4% vs 3.0% five-year average",
        "case_against": "Payout ratio 0.75 and free cash flow barely covers the dividend",
        "what_would_change_my_mind": "Two quarters of revenue growth above 3%",
        "override_reason": "Fit penalty double-counts the sector cap",
    }}

    text, title_range, bold_ranges, colored_ranges = render_analyst_text(analyses, latest_analysis)

    assert text.startswith("Analyst View")
    assert "Mondelez" in text and "MDLZ" in text
    assert VERDICT_ADD in text  # the agent's verdict, not just the computed one
    assert "Dividend safety" in text and "24" in text
    assert "Yield 4.4%" in text and "Payout ratio 0.75" in text
    assert "Two quarters of revenue growth" in text
    assert "Overridden" in text and "double-counts" in text
    assert title_range == (0, len("Analyst View"))
    assert bold_ranges and colored_ranges


def test_render_analyst_text_handles_holding_with_no_agent_entry():
    from tools.analyst import VERDICT_HOLD
    from tools.sync_summary_doc import render_analyst_text

    analyses = [{
        "ticker": "MCD", "company": "McDonald's", "is_etf": False, "verdict": VERDICT_HOLD,
        "business_view": "Neutral", "add_score": 55.0, "business_score": 55.0,
        "dividend_safety": 50.0, "quality": 60.0, "value": 55.0, "fit": 50.0,
        "strongest": ("Quality", 60.0), "weakest": ("Dividend safety", 50.0),
    }]

    text, _title, _bold, _colored = render_analyst_text(analyses, {})

    assert "McDonald's" in text
    assert "No written analysis yet" in text


def test_render_next_euro_text_lists_ranked_holdings():
    from tools.analyst import VERDICT_ADD
    from tools.sync_summary_doc import render_next_euro_text

    ranked = [
        {"rank": 1, "ticker": "BAC", "company": "Bank of America", "add_score": 72.0, "verdict": VERDICT_ADD,
         "strongest": ("Quality", 80.0), "weakest": ("Portfolio fit", 50.0)},
        {"rank": 2, "ticker": "MCD", "company": "McDonald's", "add_score": 55.0, "verdict": "Hold",
         "strongest": ("Dividend safety", 70.0), "weakest": ("Valuation", 40.0)},
    ]

    text, title_range, bold_ranges = render_next_euro_text(ranked)

    assert text.startswith("Where Your Next Euro Goes")
    assert "1. Bank of America (BAC)" in text
    assert "2. McDonald's (MCD)" in text
    assert "72" in text
    assert title_range == (0, len("Where Your Next Euro Goes"))
    assert bold_ranges


def test_render_next_euro_text_with_nothing_rankable():
    from tools.sync_summary_doc import render_next_euro_text

    text, _title, _bold = render_next_euro_text([])

    assert "not enough data" in text.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sync_summary_doc.py -v`
Expected: FAIL — `ImportError: cannot import name 'render_analyst_text'`.

- [ ] **Step 3: Implement**

Add the import `from tools.analyst import analyze_portfolio, rank_next_euro` plus, after `render_top_picks_text`, these two renderers. They follow the same `add_line` accumulator pattern as `render_top_picks_text` — read that function first and match its structure.

```python
def _score_text(value) -> str:
    return "n/a" if value is None else str(round(value))


def render_analyst_text(analyses: list[dict], latest_analysis: dict) -> tuple[str, tuple[int, int], list[tuple[int, int]], list[tuple[int, int, str]]]:
    """The "Analyst View" page: per holding, the computed sub-scores followed
    by the agent's written verdict, its case for and against, and what would
    change its mind. When the agent's verdict differs from the computed one,
    the override and its reason are printed — a disagreement is never silent."""
    lines_text: list[str] = []
    bold_ranges: list[tuple[int, int]] = []
    colored_ranges: list[tuple[int, int, str]] = []
    offset = 0

    def add_line(text: str) -> tuple[int, int]:
        nonlocal offset
        start = offset
        lines_text.append(text)
        end = start + len(text)
        offset = end + 1
        return start, end

    title_range = add_line("Analyst View")
    bold_ranges.append(title_range)
    add_line(
        "A committed opinion per holding: whether new money should go here "
        "(Add / Hold / Stop adding) and how the business itself looks "
        "(Bullish / Neutral / Bearish). Scores are computed from fetched "
        "data; the written case is the agent's judgment. This is analysis, "
        "not advice - the decision is yours."
    )
    add_line("")

    for a in analyses:
        written = latest_analysis.get(a["ticker"], {}) or {}
        verdict = written.get("verdict") or a["verdict"]
        view = written.get("business_view") or a["business_view"]

        heading_prefix = f"{a['company']} ({a['ticker']}) - "
        start, end = add_line(f"{heading_prefix}{verdict} / {view}")
        bold_ranges.append((start, end))
        colored_ranges.append((start + len(heading_prefix), end, VERDICT_COLORS.get(verdict, STATUS_COLORS["warning"])))

        confidence = written.get("confidence")
        add_line(
            f"   Add score {_score_text(a['add_score'])}/100"
            + (f" - confidence: {confidence}" if confidence else "")
        )
        add_line(
            "   Dividend safety " + _score_text(a["dividend_safety"])
            + " | Quality " + _score_text(a["quality"])
            + " | Valuation " + _score_text(a["value"])
            + " | Portfolio fit " + _score_text(a["fit"])
        )
        if a.get("is_etf"):
            add_line("   ETF: dividend-safety and quality scores do not apply; ranked on valuation and fit.")

        if written.get("case_for"):
            add_line(f"   Case for: {written['case_for']}")
        if written.get("case_against"):
            add_line(f"   Case against: {written['case_against']}")
        if written.get("what_would_change_my_mind"):
            add_line(f"   What would change my mind: {written['what_would_change_my_mind']}")
        if written.get("override_reason"):
            add_line(f"   Overridden from the computed {a['verdict']}: {written['override_reason']}")
        if not written:
            add_line("   No written analysis yet - run the analysis pass to add one.")
        add_line("")

    return "\n".join(lines_text), title_range, bold_ranges, colored_ranges


def render_next_euro_text(ranked: list[dict]) -> tuple[str, tuple[int, int], list[tuple[int, int]]]:
    """The "Where Your Next Euro Goes" page: every rankable holding ordered by
    add score, so the monthly contribution decision is one glance."""
    lines_text: list[str] = []
    bold_ranges: list[tuple[int, int]] = []
    offset = 0

    def add_line(text: str) -> tuple[int, int]:
        nonlocal offset
        start = offset
        lines_text.append(text)
        end = start + len(text)
        offset = end + 1
        return start, end

    title_range = add_line("Where Your Next Euro Goes")
    bold_ranges.append(title_range)
    add_line(
        "Holdings ranked by where new money looks best placed right now, "
        "blending dividend safety, quality, valuation and how much room is "
        "left before the position or its sector is overweight."
    )
    add_line("")

    if not ranked:
        add_line("No holding has enough data to rank yet.")
        return "\n".join(lines_text), title_range, bold_ranges

    for r in ranked:
        start, end = add_line(f"{r['rank']}. {r['company']} ({r['ticker']}) - {r['verdict']} ({round(r['add_score'])}/100)")
        bold_ranges.append((start, end))
        if r.get("strongest") and r.get("weakest"):
            add_line(f"   Strongest: {r['strongest'][0]} ({round(r['strongest'][1])}) | Weakest: {r['weakest'][0]} ({round(r['weakest'][1])})")
        add_line("")

    return "\n".join(lines_text), title_range, bold_ranges
```

Add near the other colour constants at the top of the file:

```python
VERDICT_COLORS = {
    "Add": STATUS_COLORS["good"],
    "Hold": STATUS_COLORS["warning"],
    "Stop adding": STATUS_COLORS["critical"],
    "Insufficient data": STATUS_COLORS["serious"],
}
```

(If `STATUS_COLORS` isn't already imported in this file, add it to the existing `from tools.scoring import ...` line.)

Then in `write_doc`, add both pages to `front_pages` after the Top Picks entry — `write_doc` gains `analyses` and `ranked` parameters:

```python
    analyst_text, analyst_title, analyst_bold, analyst_colored = render_analyst_text(analyses, latest_analysis)
    next_euro_text, next_euro_title, next_euro_bold = render_next_euro_text(ranked)
```

and insert into the `front_pages` list, after the top-picks tuple:

```python
        (analyst_text, analyst_title, analyst_bold, analyst_colored, []),
        (next_euro_text, next_euro_title, next_euro_bold, [], []),
```

`write_doc` needs `latest_analysis` too — pass it through from `main()`, which already builds it. In `main()`, after `allocation = compute_allocation(...)`:

```python
    analyses = analyze_portfolio(
        holdings, {h["ticker"]: (latest_fundamentals_snapshot(h["ticker"]) or {}) for h in holdings},
        latest_history, allocation,
    )
    ranked = rank_next_euro(analyses)
```

and pass `analyses`, `ranked`, `latest_analysis` into `write_doc`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q` and `python -c "import tools.sync_summary_doc"`
Expected: all PASS, clean import.

- [ ] **Step 5: Commit**

```bash
git add tools/sync_summary_doc.py tests/test_sync_summary_doc.py
git commit -m "feat: Analyst View and next-euro ranking pages in the Doc

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Workflow SOP and live verification (controller — not a subagent)

This task needs real data, Google auth and the owner's live Sheet/Doc; the orchestrating agent does it directly.

**Files:**
- Create: `workflows/analyze_portfolio.md`
- Modify: `workflows/update_portfolio.md`

- [ ] **Step 1: Refresh fundamentals so the new fields exist**

For each ticker in `data/portfolio.yaml`: `python -m tools.fetch_fundamentals --ticker <TICKER>`
Then confirm the new keys landed: `grep -c payout_ratio data/fundamentals/*.yaml`

- [ ] **Step 2: Dry-run the scoring on real data**

```bash
python -c "from tools.portfolio_lib import load_portfolio; from tools.record_snapshot import latest_history_by_ticker; from tools.fetch_fundamentals import latest_fundamentals_snapshot; from tools.allocation import compute_allocation; from tools.analyst import analyze_portfolio, rank_next_euro; h=load_portfolio(); lh=latest_history_by_ticker(); lf={x['ticker']:(latest_fundamentals_snapshot(x['ticker']) or {}) for x in h}; a=analyze_portfolio(h,lf,lh,compute_allocation(h,lh,lf)); [print(r['rank'], r['ticker'], round(r['add_score']), r['verdict'], r['business_view']) for r in rank_next_euro(a)]"
```

Sanity-check the output: holdings in an overweight sector should rank low, no verdict should read "Sell", and every ETF should still be ranked. If a score looks obviously wrong for a holding the owner knows well, investigate before writing the SOP — the thresholds are the part most likely to need tuning against reality.

- [ ] **Step 3: Write `workflows/analyze_portfolio.md`**

Cover: when it runs (after step 5 of `update_portfolio.md`); what to read per holding (sub-scores, fundamentals snapshot, the week's headlines, RSI/MACD/Konkorde, the position and sector weights); the citation rule (every number in the narrative must come from fetched data); how to pick confidence (`low` must name what's missing); the override protocol (`--computed-verdict` is always passed, `--override-reason` required to disagree, and disagreeing is legitimate when the score misses context the agent can see); the no-sell rule; and the exact `append_analysis` invocation with all judgment flags.

- [ ] **Step 4: Point `update_portfolio.md` at it**

In step 5, after the news-sentiment paragraph, add a pointer: the analysis pass now also records a verdict, business view, confidence, case for/against and what-would-change-my-mind per `workflows/analyze_portfolio.md`; the deliverable section gains a line about the Analyst tab, the Analyst View page and the next-euro ranking.

- [ ] **Step 5: Live run and verification**

```bash
python -m tools.sync_google_sheet
python -m tools.sync_summary_doc
```

Then verify via the API: the Analyst tab exists with the ranked table, Overview has Verdict/Confidence populated and coloured, the Doc has the Analyst View and Where Your Next Euro Goes pages, and re-running both tools twice leaves no duplicate tabs or pages.

- [ ] **Step 6: Final check and commit**

Run: `python -m pytest -q` — all pass.

```bash
git add workflows/analyze_portfolio.md workflows/update_portfolio.md
git commit -m "docs: add the analysis-pass SOP for analyst verdicts

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```
