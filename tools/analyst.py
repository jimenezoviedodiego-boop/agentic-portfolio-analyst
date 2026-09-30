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


def compute_dividend_safety_score(payout_ratio, dividend_rate, shares_outstanding, free_cashflow, dividend_yield=None) -> float | None:
    """Can the dividend survive? Payout ratio plus free-cash-flow cover.
    A payout above 0.75 is penalised hard per the owner's rule.
    Returns None if the company pays no dividend at all (no dividend_rate AND no dividend_yield),
    as dividend safety is not applicable for non-payers."""
    # Check if company pays any dividend: both dividend_rate and dividend_yield must be missing/zero
    if not dividend_rate and not dividend_yield:
        return None

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
        f.get("dividend_yield"),
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

    # Determine if holding pays a dividend
    pays_dividend = bool(f.get("dividend_rate") or f.get("dividend_yield"))

    # Check for fit-only case: no business sub-scores AND no valuation score
    has_no_business_or_value = (is_etf or len(business_parts) == 0) and value is None

    if has_no_business_or_value or (not is_etf and len(business_parts) < 2):
        # Too little to judge on — say so instead of guessing.
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
        "pays_dividend": pays_dividend,
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
