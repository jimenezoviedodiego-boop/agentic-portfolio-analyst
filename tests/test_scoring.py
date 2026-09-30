import pytest

from tools.scoring import (
    STATUS_COLORS,
    compute_financial_health_score,
    compute_momentum_score,
    compute_price_changes,
    compute_top_picks,
    compute_valuation_score,
    render_bar,
    score_status,
    to_float,
)


def test_to_float_handles_blank_and_numeric_strings():
    assert to_float(None) is None
    assert to_float("") is None
    assert to_float("62.50") == pytest.approx(62.5)
    assert to_float(70) == 70.0


def _price_row(date_str, close):
    return {"date": date_str, "close": str(close)}


def test_compute_price_changes_day_week_month():
    rows = [
        _price_row("2026-08-17", 100.0),
        _price_row("2026-09-09", 110.0),
        _price_row("2026-09-15", 120.0),
        _price_row("2026-09-16", 132.0),
    ]
    changes = compute_price_changes(rows)
    # day: (132-120)/120 = 10%; week: closest close on/before 2026-09-09 is
    # 110 -> (132-110)/110 = 20%; month: closest close on/before 2026-08-17
    # (exactly 30 days back) is 100 -> (132-100)/100 = 32%.
    assert changes["day_change_pct"] == pytest.approx(10.0)
    assert changes["week_change_pct"] == pytest.approx(20.0)
    assert changes["month_change_pct"] == pytest.approx(32.0)


def test_compute_price_changes_missing_history_returns_none():
    assert compute_price_changes([]) == {
        "day_change_pct": None,
        "week_change_pct": None,
        "month_change_pct": None,
    }
    single = compute_price_changes([_price_row("2026-09-16", 100.0)])
    assert single == {"day_change_pct": None, "week_change_pct": None, "month_change_pct": None}


def test_compute_price_changes_uses_closest_prior_trading_day():
    # Only two rows, 3 days apart — well short of a full week/month, so those windows are None,
    # but "day" change still uses the most recent prior close available.
    rows = [_price_row("2026-09-13", 90.0), _price_row("2026-09-16", 99.0)]
    changes = compute_price_changes(rows)
    assert changes["day_change_pct"] == pytest.approx(10.0)
    assert changes["week_change_pct"] is None
    assert changes["month_change_pct"] is None


def test_compute_valuation_score_at_52_week_low_scores_high():
    score = compute_valuation_score(
        price_local=100.0, fifty_two_week_low=100.0, fifty_two_week_high=200.0,
        pe_ratio=None, forward_pe=None,
    )
    assert score == pytest.approx(100.0)


def test_compute_valuation_score_at_52_week_high_scores_low():
    score = compute_valuation_score(
        price_local=200.0, fifty_two_week_low=100.0, fifty_two_week_high=200.0,
        pe_ratio=None, forward_pe=None,
    )
    assert score == pytest.approx(0.0)


def test_compute_valuation_score_blends_pe_discount():
    # Mid-range price (range component = 50) plus a forward P/E well below
    # trailing (expected earnings growth) should push the blended score above 50.
    score = compute_valuation_score(
        price_local=150.0, fifty_two_week_low=100.0, fifty_two_week_high=200.0,
        pe_ratio=20.0, forward_pe=15.0,
    )
    assert score > 50.0


def test_compute_valuation_score_returns_none_with_no_usable_inputs():
    assert compute_valuation_score(
        price_local=100.0, fifty_two_week_low=None, fifty_two_week_high=None,
        pe_ratio=None, forward_pe=None,
    ) is None


def test_compute_momentum_score_boundaries_and_clamp():
    assert compute_momentum_score(None) is None
    assert compute_momentum_score(0.0) == pytest.approx(50.0)
    assert compute_momentum_score(20.0) == pytest.approx(100.0)
    assert compute_momentum_score(-20.0) == pytest.approx(0.0)
    assert compute_momentum_score(50.0) == pytest.approx(100.0)  # clamped
    assert compute_momentum_score(-50.0) == pytest.approx(0.0)  # clamped


def test_compute_financial_health_score_blends_debt_and_margin():
    score = compute_financial_health_score(debt_to_equity=0.0, profit_margin=0.20)
    assert score == pytest.approx(100.0)

    score_high_debt = compute_financial_health_score(debt_to_equity=300.0, profit_margin=0.0)
    assert score_high_debt == pytest.approx(0.0)


def test_compute_financial_health_score_none_when_no_inputs():
    assert compute_financial_health_score(debt_to_equity=None, profit_margin=None) is None


def test_score_status_bands():
    assert score_status(None) is None
    assert score_status(90) == ("good", "Strong Buy")
    assert score_status(75) == ("good", "Strong Buy")
    assert score_status(60) == ("warning", "Buy")
    assert score_status(30) == ("serious", "Hold")
    assert score_status(10) == ("critical", "Sell")
    assert score_status(0) == ("critical", "Sell")


def test_render_bar_fill_proportional_to_score():
    assert render_bar(None) == "░" * 10
    assert render_bar(0) == "░" * 10
    assert render_bar(100) == "█" * 10
    assert render_bar(72) == "█" * 7 + "░" * 3
    assert render_bar(50, width=4) == "██░░"


def test_compute_top_picks_ranks_by_overall_score_descending():
    holdings = [
        {"ticker": "AAA", "company": "Weakest Co"},
        {"ticker": "BBB", "company": "Strongest Co"},
        {"ticker": "CCC", "company": "Middle Co"},
    ]
    latest_history = {
        "AAA": {"valuation_score": "20.00", "momentum_score": "20.00", "financial_health_score": "20.00"},
        "BBB": {"valuation_score": "90.00", "momentum_score": "80.00", "financial_health_score": "85.00"},
        "CCC": {"valuation_score": "50.00", "momentum_score": "50.00", "financial_health_score": "50.00"},
    }
    latest_analysis = {
        "AAA": {"news_sentiment_score": 20},
        "BBB": {"news_sentiment_score": 90},
        "CCC": {"news_sentiment_score": 50},
    }

    picks = compute_top_picks(holdings, latest_history, latest_analysis, top_n=2)

    assert [p["ticker"] for p in picks] == ["BBB", "CCC"]
    assert picks[0]["overall_status"] == ("good", "Strong Buy")
    assert picks[0]["top_dimension_label"] == "Valuation"  # 90 is BBB's highest dimension
    assert picks[0]["top_dimension_score"] == 90.0


def test_compute_top_picks_skips_holdings_with_no_scores_at_all():
    holdings = [{"ticker": "NODATA", "company": "No Data Co"}, {"ticker": "HASDATA", "company": "Has Data Co"}]
    latest_history = {"HASDATA": {"valuation_score": "60.00"}}

    picks = compute_top_picks(holdings, latest_history, {}, top_n=5)

    assert [p["ticker"] for p in picks] == ["HASDATA"]


def test_status_colors_has_all_four_bands():
    assert set(STATUS_COLORS.keys()) == {"good", "warning", "serious", "critical"}
    for hex_value in STATUS_COLORS.values():
        assert hex_value.startswith("#") and len(hex_value) == 7
