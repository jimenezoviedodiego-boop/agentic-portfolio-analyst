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
    # With dividend_rate, can compute from just payout ratio (no FCF cover component)
    only_payout = compute_dividend_safety_score(payout_ratio=0.75, dividend_rate=0.01, shares_outstanding=None, free_cashflow=None)
    assert only_payout == pytest.approx(41.667, abs=0.01)
    # Without dividend evidence (rate or yield), returns None even with payout_ratio
    assert compute_dividend_safety_score(payout_ratio=0.75, dividend_rate=None, shares_outstanding=None, free_cashflow=None, dividend_yield=None) is None
    assert compute_dividend_safety_score(None, None, None, None) is None


def test_dividend_safety_payer_with_zero_payout():
    # A payer with zero payout but real dividend_rate: treat as a real data point, not a non-payer.
    assert compute_dividend_safety_score(0.0, 2.0, 1_000_000_000, 5_000_000_000) == pytest.approx(100.0)


def test_dividend_safety_non_payer_returns_none():
    # AMZN/KD profile: payout 0.0 with no dividend_rate or dividend_yield = non-payer.
    # Should return None, not 100, because dividend safety doesn't apply to non-payers.
    assert compute_dividend_safety_score(0.0, None, 1_000_000_000, 5_000_000_000, None) is None
    # Also test with dividend_yield explicitly zero
    assert compute_dividend_safety_score(0.0, 0.0, 1_000_000_000, 5_000_000_000, 0.0) is None
    # Non-None dividend_rate makes it a payer, even if payout_ratio is 0
    assert compute_dividend_safety_score(0.0, 0.01, 1_000_000_000, 5_000_000_000, None) is not None
    # Non-None dividend_yield makes it a payer
    assert compute_dividend_safety_score(0.0, None, 1_000_000_000, 5_000_000_000, 0.01) is not None


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
    # dividend_safety missing (non-payer) -> weights renormalise over 0.70
    # (0.30*60 + 0.25*80 + 0.15*50) / 0.70
    expected_no_div = (0.30 * 60 + 0.25 * 80 + 0.15 * 50) / 0.70
    assert compute_add_score(None, 60.0, 80.0, 50.0) == pytest.approx(expected_no_div, abs=0.01)
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
    assert result["pays_dividend"] is True


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


def test_analyze_holding_non_payer_renormalizes_score():
    # AMZN-like: payout_ratio=0.0 with no dividend rate/yield = non-payer
    holding = {"ticker": "AMZN", "company": "Amazon", "is_etf": False}
    fundamentals = {
        "payout_ratio": 0.0, "dividend_rate": None, "dividend_yield": None,
        "shares_outstanding": 1_000_000_000, "free_cashflow": 5_000_000_000,
        "profit_margin": 0.10, "operating_margins": 0.15, "revenue_growth": 0.05, "earnings_growth": 0.10,
        "debt_to_equity": 40.0, "current_ratio": 1.2,
        "pe_ratio": 15.0, "forward_pe": 12.0, "price_to_book": 2.0, "target_mean_price": 100.0,
    }

    result = analyze_holding(holding, fundamentals, price_local=80.0, position_weight_pct=8.0, sector_weight_pct=20.0)

    assert result["dividend_safety"] is None  # Non-payer
    assert result["pays_dividend"] is False
    assert result["quality"] is not None  # But still has quality score
    assert result["value"] is not None  # And value score
    # add_score should renormalize: quality and value and fit available, dividend_safety not
    assert result["add_score"] is not None
    # With 3 scores (quality, value, fit) but only quality and value non-None, renormalization happens


def test_analyze_holding_etf_fit_only_is_insufficient():
    # VWRL-like: ETF with NO valuation components at all = fit is only score
    holding = {"ticker": "VWRL.AS", "company": "Vanguard FTSE All-World", "is_etf": True}
    fundamentals = {}  # No valuation data at all

    result = analyze_holding(holding, fundamentals, price_local=None, position_weight_pct=14.3, sector_weight_pct=14.3)

    assert result["value"] is None  # No valuation data
    assert result["fit"] is not None  # Has fit score
    assert result["add_score"] is None  # Fit-only case: no ranking
    assert result["verdict"] == VERDICT_INSUFFICIENT
    assert result["business_view"] == VERDICT_INSUFFICIENT


def test_analyze_holding_non_etf_fit_only_is_insufficient():
    # Non-ETF with NO business data and NO valuation data = fit is only score
    holding = {"ticker": "UNKNOWN", "company": "Mystery Stock", "is_etf": False}
    fundamentals = {}  # No data at all

    result = analyze_holding(holding, fundamentals, price_local=100.0, position_weight_pct=5.0, sector_weight_pct=10.0)

    assert result["dividend_safety"] is None
    assert result["quality"] is None
    assert result["value"] is None
    assert result["fit"] is not None  # Has fit score
    assert result["add_score"] is None  # Fit-only case: no ranking
    assert result["verdict"] == VERDICT_INSUFFICIENT


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
