import argparse
from datetime import date
from pathlib import Path

from tools.analyst import BUSINESS_VIEWS, CONFIDENCE_LEVELS, VERDICTS
from tools.portfolio_lib import append_yaml_list, data_dir


def analysis_yaml_path(ticker: str) -> Path:
    return data_dir() / "analysis" / f"{ticker}.yaml"


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
    if verdict is not None and computed_verdict is None:
        raise ValueError(
            f"computed_verdict is required when verdict is supplied (pass --computed-verdict so the verdict "
            "is cross-checked against the scoring engine's verdict)"
        )
    if verdict is not None and computed_verdict is not None and verdict != computed_verdict:
        # Strip override_reason to detect whitespace-only reasons
        reason = override_reason.strip() if override_reason else None
        if not reason:
            raise ValueError(
                f"verdict {verdict!r} differs from the computed verdict {computed_verdict!r} — "
                "override_reason is required: pass --override-reason explaining why the score is wrong here"
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--price-change-pct", type=float, required=True)
    parser.add_argument("--window", required=True)
    parser.add_argument("--price-narrative", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--watch", required=True)
    parser.add_argument("--news-sentiment-score", type=int, required=True)
    parser.add_argument("--verdict", choices=VERDICTS)
    parser.add_argument("--business-view", choices=BUSINESS_VIEWS)
    parser.add_argument("--confidence", choices=CONFIDENCE_LEVELS)
    parser.add_argument("--case-for")
    parser.add_argument("--case-against")
    parser.add_argument("--what-would-change-my-mind")
    parser.add_argument("--override-reason")
    parser.add_argument("--computed-verdict", choices=VERDICTS,
                        help="the verdict tools.analyst computed; required whenever --verdict is supplied so the verdict is cross-checked against the scoring engine's verdict")
    args = parser.parse_args()

    entry = build_entry(
        args.price_change_pct, args.window, args.price_narrative, args.status, args.watch,
        args.news_sentiment_score,
        verdict=args.verdict, business_view=args.business_view, confidence=args.confidence,
        case_for=args.case_for, case_against=args.case_against,
        what_would_change_my_mind=args.what_would_change_my_mind,
        override_reason=args.override_reason, computed_verdict=args.computed_verdict,
    )
    append_yaml_list(analysis_yaml_path(args.ticker), entry, "entries")
    print(f"Appended analysis entry for {args.ticker} on {entry['date']}")


if __name__ == "__main__":
    main()
