import pytest

from tools.analyst import VERDICT_ADD, VERDICT_HOLD, VIEW_BULLISH
from tools.append_analysis import build_entry


def test_build_entry_has_expected_shape():
    entry = build_entry(
        price_change_pct=4.2,
        window="since 2026-09-09",
        price_narrative="Up 4% this week on strong sell-through reports.",
        status="Valuation reasonable at 22x P/E.",
        watch="Earnings call on 2026-10-15.",
        news_sentiment_score=70,
        today_str="2026-09-16",
    )
    assert entry == {
        "date": "2026-09-16",
        "price_change_pct": 4.2,
        "window": "since 2026-09-09",
        "price_narrative": "Up 4% this week on strong sell-through reports.",
        "status": "Valuation reasonable at 22x P/E.",
        "watch": "Earnings call on 2026-10-15.",
        "news_sentiment_score": 70,
    }


def test_build_entry_rejects_out_of_range_sentiment_score():
    with pytest.raises(ValueError):
        build_entry(
            price_change_pct=1.0, window="w", price_narrative="p",
            status="s", watch="w", news_sentiment_score=150,
        )
    with pytest.raises(ValueError):
        build_entry(
            price_change_pct=1.0, window="w", price_narrative="p",
            status="s", watch="w", news_sentiment_score=-1,
        )


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


def test_build_entry_requires_computed_verdict_when_verdict_supplied():
    """Guardrail is enforced: computed_verdict required whenever verdict is supplied."""
    with pytest.raises(ValueError, match="computed_verdict"):
        build_entry(**_base_kwargs(), verdict=VERDICT_ADD)


def test_build_entry_rejects_whitespace_only_override_reason():
    """Whitespace-only override_reason is treated as no reason and rejected."""
    with pytest.raises(ValueError, match="override_reason"):
        build_entry(
            **_base_kwargs(), verdict=VERDICT_ADD, computed_verdict=VERDICT_HOLD,
            override_reason="   ",
        )


def test_build_entry_rejects_unknown_business_view():
    with pytest.raises(ValueError, match="business_view"):
        build_entry(**_base_kwargs(), business_view="Very Bullish")
