from datetime import date, timedelta

# Fixed status palette (from the dataviz skill's validated reference palette,
# references/palette.md "Status palette (fixed - never themed)") — never
# reused for anything else, and always paired with a number/label in the
# UI, never color alone.
STATUS_COLORS = {
    "good": "#0ca30c",
    "warning": "#fab219",
    "serious": "#ec835a",
    "critical": "#d03b3b",
}

# (score >= threshold, status_key, status_label), checked highest-first.
# Labels are investment-action language, not severity language — the point
# of every score in this project is "should I add more money to this
# holding," so the label should answer that directly. status_key (used for
# STATUS_COLORS lookups) stays as-is; only the displayed text changed.
STATUS_BANDS = [
    (75, "good", "Strong Buy"),
    (50, "warning", "Buy"),
    (25, "serious", "Hold"),
    (0, "critical", "Sell"),
]

DELTA_UP_COLOR = "#006300"
DELTA_DOWN_COLOR = "#d03b3b"

# Shared by both sync tools: (field name, display label, source). "history"
# scores are computed deterministically by record_snapshot; news_sentiment_score
# lives on the analysis entry instead, since it's the agent's own judgment
# of the week's headlines, not a formula.
SCORE_FIELDS = [
    ("valuation_score", "Valuation", "history"),
    ("momentum_score", "Momentum", "history"),
    ("financial_health_score", "Fin. Health", "history"),
    ("news_sentiment_score", "News Sentiment", "analysis"),
]


def to_float(value) -> float | None:
    """Converts a possibly-blank string or numeric value (as stored in CSV/YAML
    fields, e.g. "" or "62.50") to float, or None if it's blank/missing."""
    if value is None or value == "":
        return None
    return float(value)


def _closest_close_on_or_before(sorted_rows: list[dict], target_date: date) -> float | None:
    candidates = [r for r in sorted_rows if date.fromisoformat(r["date"]) <= target_date]
    if not candidates:
        return None
    return float(candidates[-1]["close"])


def compute_price_changes(price_rows: list[dict]) -> dict:
    sorted_rows = sorted(price_rows, key=lambda r: r["date"])
    if not sorted_rows:
        return {"day_change_pct": None, "week_change_pct": None, "month_change_pct": None}

    latest = sorted_rows[-1]
    latest_date = date.fromisoformat(latest["date"])
    latest_close = float(latest["close"])
    prior_rows = sorted_rows[:-1]

    day_change = None
    if prior_rows:
        prev_close = float(prior_rows[-1]["close"])
        day_change = (latest_close - prev_close) / prev_close * 100

    week_close = _closest_close_on_or_before(prior_rows, latest_date - timedelta(days=7))
    week_change = (latest_close - week_close) / week_close * 100 if week_close else None

    month_close = _closest_close_on_or_before(prior_rows, latest_date - timedelta(days=30))
    month_change = (latest_close - month_close) / month_close * 100 if month_close else None

    return {
        "day_change_pct": day_change,
        "week_change_pct": week_change,
        "month_change_pct": month_change,
    }


def compute_valuation_score(
    price_local: float,
    fifty_two_week_low: float | None,
    fifty_two_week_high: float | None,
    pe_ratio: float | None,
    forward_pe: float | None,
) -> float | None:
    """0-100, higher = more attractively valued right now.

    Blends where the price sits in its own 52-week range (nearer the low is
    cheaper) with the forward-vs-trailing P/E gap (a cheaper forward P/E
    implies expected earnings growth). Either component is used alone if the
    other's inputs are missing (e.g. an ETF with no P/E)."""
    components = []

    if fifty_two_week_low is not None and fifty_two_week_high is not None and fifty_two_week_high > fifty_two_week_low:
        range_position = (price_local - fifty_two_week_low) / (fifty_two_week_high - fifty_two_week_low)
        range_position = max(0.0, min(1.0, range_position))
        components.append(100 * (1 - range_position))

    if pe_ratio and forward_pe and pe_ratio > 0:
        pe_discount = (pe_ratio - forward_pe) / pe_ratio
        components.append(max(0.0, min(100.0, 50 + pe_discount * 100)))

    if not components:
        return None
    return sum(components) / len(components)


def compute_momentum_score(month_change_pct: float | None) -> float | None:
    """0-100, mapping -20% -> 0, 0% -> 50, +20% -> 100, clamped beyond."""
    if month_change_pct is None:
        return None
    score = 50 + (month_change_pct / 20) * 50
    return max(0.0, min(100.0, score))


def compute_financial_health_score(debt_to_equity: float | None, profit_margin: float | None) -> float | None:
    """0-100, blending lower debt/equity (better) and higher profit margin (better)."""
    components = []

    if debt_to_equity is not None:
        components.append(100 - max(0.0, min(100.0, debt_to_equity / 300 * 100)))

    if profit_margin is not None:
        components.append(max(0.0, min(100.0, profit_margin * 100 * 5)))

    if not components:
        return None
    return sum(components) / len(components)


# Shared explanatory content for both deliverables (Sheet legend tab, Doc
# legend page) — one source of truth so the wording never drifts between
# the two. Each entry is (term, plain-language explanation).
LEGEND_SECTIONS = [
    (
        "Current Value",
        "The position's total worth today: shares owned x current price, "
        "converted to EUR at today's FX rate. This is not money added or "
        "withdrawn - it's simply what the position is worth right now.",
    ),
    (
        "G/P (Gain/Loss)",
        "Unrealized gain or loss versus the average cost basis: Current "
        "Value minus (shares x average cost). Shown in EUR and as a "
        "percentage. This is 'paper' gain/loss - it only becomes real if "
        "the position is sold.",
    ),
    (
        "Day / Week / Month %",
        "The price change over the last trading day, roughly the last 7 "
        "calendar days, and roughly the last 30 calendar days, using each "
        "ticker's own cached price history.",
    ),
    (
        "Valuation score (0-100)",
        "Computed automatically. Higher means the stock looks cheaper "
        "right now: it blends where the price sits in its own 52-week "
        "range (nearer the low scores higher) with the forward-vs-trailing "
        "P/E gap (a cheaper forward P/E implies expected earnings growth).",
    ),
    (
        "Momentum score (0-100)",
        "Computed automatically from the past month's price change: -20% "
        "or worse scores 0, flat (0%) scores 50, +20% or better scores 100.",
    ),
    (
        "Financial Health score (0-100)",
        "Computed automatically from the company's debt-to-equity ratio "
        "(lower is better) and profit margin (higher is better).",
    ),
    (
        "News Sentiment score (0-100)",
        "The one score that is not a formula - it's the agent's own "
        "reading of that week's fetched headlines: 50 means neutral or too "
        "little news to judge, higher means coverage skews positive, lower "
        "means it skews negative.",
    ),
    (
        "Overall",
        "The average of whichever of the 4 scores above are actually "
        "available for that holding.",
    ),
    (
        "Rating bands (Sell / Hold / Buy / Strong Buy)",
        "Every score, including Overall, falls into one of four even "
        "buckets over the 0-100 scale: Sell 0-24, Hold 25-49, Buy 50-74, "
        "Strong Buy 75-100 - colored red to green. This is a reading of "
        "the numbers as computed, not investment advice - always sanity "
        "check it against the News/Fundamentals/Watch text before acting.",
    ),
    (
        "Allocation (% of portfolio / Put in)",
        "How today's total value splits by sector, country and position. "
        "'% of portfolio' is a holding's Current Value divided by the whole "
        "portfolio's value. 'Put in' is what you paid (Current Value minus "
        "G/P, i.e. shares x average cost, converted at today's FX rate - so "
        "approximate for non-EUR holdings) - comparing the two shows whether a big position is big because "
        "you invested a lot or because it grew. Sector and country come from "
        "Yahoo Finance; the ETF is listed as its own group. Positions above "
        "10% and sectors above 25% are flagged as a rule of thumb.",
    ),
    (
        "Where the data comes from",
        "Prices and company fundamentals (P/E, debt, margins, 52-week "
        "range) come from Yahoo Finance. News headlines come from Google "
        "News. Everything is refreshed each time the portfolio is updated.",
    ),
]


def render_bar(score: float | None, width: int = 10) -> str:
    """Unicode block bar for monospace rendering, e.g. '███████░░░' for a 72/100 score."""
    if score is None:
        return "░" * width
    filled = max(0, min(width, round(score / 100 * width)))
    return "█" * filled + "░" * (width - filled)


def compute_top_picks(
    holdings: list[dict],
    latest_history: dict[str, dict],
    latest_analysis: dict[str, dict],
    top_n: int = 5,
) -> list[dict]:
    """Ranks holdings by Overall score (mean of whichever of the 4 SCORE_FIELDS
    are available), descending, and returns the top_n. Each result also names
    its single highest-scoring dimension, as a concrete one-line "why" rather
    than a generic ranking. Holdings with no scores available at all (e.g. no
    data fetched yet) are skipped, not ranked last with a fabricated score."""
    ranked = []
    for h in holdings:
        hist = latest_history.get(h["ticker"], {})
        analysis = latest_analysis.get(h["ticker"], {})

        dimension_scores = {}
        for key, label, source in SCORE_FIELDS:
            current = hist if source == "history" else analysis
            score = to_float(current.get(key))
            if score is not None:
                dimension_scores[label] = score

        if not dimension_scores:
            continue

        overall_score = sum(dimension_scores.values()) / len(dimension_scores)
        top_dimension_label, top_dimension_score = max(dimension_scores.items(), key=lambda kv: kv[1])

        ranked.append(
            {
                "ticker": h["ticker"],
                "company": h["company"],
                "overall_score": overall_score,
                "overall_status": score_status(overall_score),
                "top_dimension_label": top_dimension_label,
                "top_dimension_score": top_dimension_score,
            }
        )

    ranked.sort(key=lambda r: r["overall_score"], reverse=True)
    return ranked[:top_n]


def score_status(score: float | None) -> tuple[str, str] | None:
    """Maps a 0-100 score to (status_key, status_label), or None if score is None."""
    if score is None:
        return None
    for threshold, key, label in STATUS_BANDS:
        if score >= threshold:
            return key, label
    return "critical", "Sell"
