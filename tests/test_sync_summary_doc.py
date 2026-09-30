from tools.sync_summary_doc import build_summary_sections, render_legend_text, render_section_text, render_top_picks_text


def test_build_summary_sections_includes_status_and_watch():
    holdings = [{"ticker": "HON", "company": "Honeywell International", "shares": 10}]
    latest_analysis = {
        "HON": {
            "status": "Valuation reasonable at 22x P/E.",
            "price_narrative": "Up 4% this week on strong sell-through.",
            "watch": "Earnings call 2026-10-15.",
            "news_sentiment_score": 70,
        }
    }
    latest_history = {
        "HON": {
            "value_eur": "1500.00", "gp_eur": "250.00", "gp_pct": "20.00",
            "valuation_score": "62.50", "momentum_score": "70.00", "financial_health_score": "80.00",
        }
    }

    sections = build_summary_sections(holdings, latest_analysis, latest_history, {}, {})

    assert len(sections) == 1
    s = sections[0]
    assert s["heading"] == "Honeywell International (HON)"
    assert "1500.00" in s["summary_line"]
    assert "Current Value" in s["summary_line"]
    assert "250.00" in s["summary_line"]
    assert s["status_text"] == "Valuation reasonable at 22x P/E."
    assert s["price_narrative"] == "Up 4% this week on strong sell-through."
    assert s["watch"] == "Earnings call 2026-10-15."
    assert s["overall_status"] is not None  # (62.5+70+80+70)/4 = 70.625 -> warning band
    assert s["overall_status"][0] == "warning"
    assert s["overall_score"] == 70.625

    score_by_label = {line["label"]: line for line in s["score_lines"]}
    assert score_by_label["Valuation"]["score"] == 62.5
    assert score_by_label["Valuation"]["status"] == ("warning", "Buy")
    assert score_by_label["News Sentiment"]["score"] == 70


def test_build_summary_sections_handles_missing_analysis():
    holdings = [{"ticker": "KD", "company": "Kyndryl Holdings", "shares": 3}]
    sections = build_summary_sections(holdings, {}, {}, {}, {})
    s = sections[0]
    assert s["status_text"] == "No status recorded yet."
    assert s["overall_status"] is None
    assert s["overall_score"] is None
    for line in s["score_lines"]:
        assert line["score"] is None
        assert line["status"] is None


def test_build_summary_sections_includes_previous_run_comparison():
    holdings = [{"ticker": "HON", "company": "Honeywell International", "shares": 10}]
    latest_history = {"HON": {"value_eur": "1500.00", "gp_eur": "250.00", "gp_pct": "20.00", "valuation_score": "70.00"}}
    previous_history = {"HON": {"valuation_score": "58.00"}}
    latest_analysis = {"HON": {"news_sentiment_score": 60}}
    previous_analysis = {"HON": {"news_sentiment_score": 45}}

    sections = build_summary_sections(holdings, latest_analysis, latest_history, previous_analysis, previous_history)
    score_by_label = {line["label"]: line for line in sections[0]["score_lines"]}

    assert score_by_label["Valuation"]["previous_score"] == 58.0
    assert score_by_label["News Sentiment"]["previous_score"] == 45
    assert score_by_label["Momentum"]["previous_score"] is None  # no previous data for this dimension


def test_render_section_text_produces_bar_lines_and_color_ranges():
    section = {
        "heading": "Honeywell International (HON)",
        "summary_line": "Shares: 10  |  Current Value: 1500.00 EUR  |  G/P: 250.00 EUR (20.00%)",
        "overall_status": ("warning", "Buy"),
        "overall_score": 70.625,
        "score_lines": [
            {"label": "Valuation", "score": 62.5, "previous_score": 58.0, "status": ("warning", "Buy")},
            {"label": "Momentum", "score": None, "previous_score": None, "status": None},
        ],
        "status_text": "Some status.",
        "price_narrative": "Some narrative.",
        "watch": "Some watch item.",
    }

    text, colored_ranges, heading_range, monospace_ranges, bold_ranges = render_section_text(section)

    assert text.startswith("Honeywell International (HON)\n")
    assert "Valuation" in text
    assert "62/100" in text  # rounded score
    assert "(last: 58)" in text
    assert "n/a" in text  # the missing Momentum score
    assert text.count("(last:") == 1  # only the populated score gets a comparison

    # the three content blocks are explicitly labeled, not one undifferentiated paragraph
    assert "News" in text
    assert "Fundamentals" in text
    assert "Watch" in text
    assert "Some narrative." in text
    assert "Some status." in text
    assert "Some watch item." in text

    # Overall shows both the label and the raw score, so band names are never opaque
    assert "Overall: Buy (71/100)" in text

    # heading_range covers exactly the heading line
    assert text[heading_range[0]:heading_range[1]] == "Honeywell International (HON)"

    # every colored range's text slice is non-empty and inside the section text
    for start, end, hex_color in colored_ranges:
        assert 0 <= start < end <= len(text)
        assert hex_color.startswith("#")

    # bar lines are flagged for monospace font
    assert len(monospace_ranges) == 2  # both score lines (Valuation + Momentum), even the "n/a" one
    for start, end in monospace_ranges:
        assert 0 <= start < end <= len(text)

    # the News/Fundamentals/Watch mini-labels are bolded so they read as
    # distinct blocks rather than one dense paragraph
    bolded_texts = {text[s:e] for s, e in bold_ranges}
    assert "News" in bolded_texts
    assert "Fundamentals" in bolded_texts
    assert "Watch" in bolded_texts
    for start, end in bold_ranges:
        assert 0 <= start < end <= len(text)


def test_render_top_picks_text_lists_rank_reason_and_colors_the_rating():
    picks = [
        {
            "ticker": "SAN.PA", "company": "Sanofi SA", "overall_score": 91.4,
            "overall_status": ("good", "Strong Buy"),
            "top_dimension_label": "Valuation", "top_dimension_score": 89.0,
        },
        {
            "ticker": "BAC", "company": "Bank of America Corp", "overall_score": 62.0,
            "overall_status": ("warning", "Buy"),
            "top_dimension_label": "Financial Health", "top_dimension_score": 100.0,
        },
    ]

    text, colored_ranges, title_range, bold_ranges = render_top_picks_text(picks)

    assert text[title_range[0]:title_range[1]] == "Top Picks"
    assert "1. Sanofi SA (SAN.PA) - Strong Buy (91/100)" in text
    assert "Strongest signal: Valuation (89/100)" in text
    assert "2. Bank of America Corp (BAC) - Buy (62/100)" in text
    assert "Strongest signal: Financial Health (100/100)" in text

    assert len(colored_ranges) == 2
    for start, end, hex_color in colored_ranges:
        assert 0 <= start < end <= len(text)
        assert hex_color.startswith("#")

    bolded_texts = {text[s:e] for s, e in bold_ranges}
    assert "Top Picks" in bolded_texts


def test_render_top_picks_text_handles_no_ranked_holdings():
    text, colored_ranges, title_range, bold_ranges = render_top_picks_text([])
    assert "No holdings have enough data yet to rank." in text
    assert colored_ranges == []


def test_render_legend_text_covers_every_documented_term():
    from tools.scoring import LEGEND_SECTIONS

    text, bold_ranges, title_range = render_legend_text()

    assert text[title_range[0]:title_range[1]] == "How to Read This Report"
    for term, _explanation in LEGEND_SECTIONS:
        assert term in text

    bolded_texts = {text[s:e] for s, e in bold_ranges}
    assert "How to Read This Report" in bolded_texts
    for term, _explanation in LEGEND_SECTIONS:
        assert term in bolded_texts
    for start, end in bold_ranges:
        assert 0 <= start < end <= len(text)


def _allocation_fixture():
    from tools.allocation import compute_allocation
    holdings = [
        {"ticker": "AAA", "company": "Alpha Health"},
        {"ticker": "BBB", "company": "Beta Foods"},
    ]
    history = {"AAA": {"value_eur": "800", "gp_eur": "600"}, "BBB": {"value_eur": "200", "gp_eur": "0"}}
    fundamentals = {
        "AAA": {"quote_type": "EQUITY", "sector": "Healthcare", "country": "United States"},
        "BBB": {"quote_type": "EQUITY", "sector": "Consumer Defensive", "country": "France"},
    }
    return compute_allocation(holdings, history, fundamentals)


def test_render_allocation_text_shows_sectors_countries_positions_and_flags():
    from tools.sync_summary_doc import render_allocation_text
    text, title_range, bold_ranges, monospace_ranges = render_allocation_text(_allocation_fixture())

    assert text[title_range[0]:title_range[1]] == "Portfolio Allocation"
    for heading in ("By sector", "By country", "By position", "Concentration check"):
        assert heading in text
        assert any(text[s:e] == heading for s, e in bold_ranges)

    mono_lines = [text[s:e] for s, e in monospace_ranges]
    healthcare = next(l for l in mono_lines if l.startswith("Healthcare"))
    assert "80.0%" in healthcare and "AAA" in healthcare
    assert "█" in healthcare
    assert any(l.startswith("France") and "20.0%" in l for l in mono_lines)
    assert any(l.startswith("AAA") and "Alpha Health" in l for l in mono_lines)

    # Concentration flags are listed (AAA at 80% breaks the position rule).
    assert "(AAA)" in text.split("Concentration check", 1)[1]


def test_render_allocation_text_scales_bars_to_the_largest_group():
    from tools.sync_summary_doc import render_allocation_text
    text, _title, _bold, monospace_ranges = render_allocation_text(_allocation_fixture())
    healthcare = next(text[s:e] for s, e in monospace_ranges if text[s:e].startswith("Healthcare"))
    # The largest group gets a full bar, so small weights stay visually comparable.
    assert "░" not in healthcare.split("%")[0]


def test_render_analyst_text_shows_verdict_case_and_override():
    from tools.analyst import VERDICT_ADD, VERDICT_HOLD
    from tools.sync_summary_doc import VERDICT_COLORS, render_analyst_text

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

    # bold_ranges: the per-holding heading line, sliced at its offsets, is
    # exactly the expected text (not merely present somewhere in the page).
    heading_start, heading_end = next((s, e) for s, e in bold_ranges if (s, e) != title_range)
    assert text[heading_start:heading_end] == f"Mondelez (MDLZ) - {VERDICT_ADD} / Neutral"

    # colored_ranges: only the verdict word itself is coloured, not the
    # business view next to it — the two judgments are independent.
    verdict_start, verdict_end, hex_color = colored_ranges[0]
    assert text[verdict_start:verdict_end] == VERDICT_ADD
    assert hex_color == VERDICT_COLORS[VERDICT_ADD]


def test_render_analyst_text_override_names_the_stored_computed_verdict():
    """The override line must audit against what the score said AT THE TIME
    the agent recorded the override (computed_verdict), not against today's
    recomputed verdict — those drift apart because Doc syncs run more often
    than analysis passes."""
    from tools.analyst import VERDICT_ADD
    from tools.sync_summary_doc import render_analyst_text

    analyses = [{
        "ticker": "MDLZ", "company": "Mondelez", "is_etf": False,
        "verdict": "Hold",  # today's recomputed verdict — must NOT appear in the override line
        "business_view": "Neutral", "add_score": 56.3, "business_score": 59.7,
        "dividend_safety": 23.8, "quality": 81.7, "value": 73.8, "fit": 41.7,
        "strongest": ("Quality", 81.7), "weakest": ("Dividend safety", 23.8),
    }]
    latest_analysis = {"MDLZ": {
        "verdict": VERDICT_ADD, "business_view": "Neutral",
        "computed_verdict": "Stop adding",  # what the score said when the override was recorded
        "override_reason": "Fit penalty double-counts the sector cap",
    }}

    text, _title, _bold, _colored = render_analyst_text(analyses, latest_analysis)

    assert "Overridden from the computed Stop adding:" in text
    assert "Overridden from the computed Hold:" not in text


def test_render_analyst_text_override_falls_back_when_computed_verdict_missing():
    """Older entries predate the computed_verdict field — fall back to the
    recomputed verdict rather than crashing or silently omitting the line."""
    from tools.analyst import VERDICT_ADD
    from tools.sync_summary_doc import render_analyst_text

    analyses = [{
        "ticker": "MDLZ", "company": "Mondelez", "is_etf": False, "verdict": "Hold",
        "business_view": "Neutral", "add_score": 56.3, "business_score": 59.7,
        "dividend_safety": 23.8, "quality": 81.7, "value": 73.8, "fit": 41.7,
        "strongest": ("Quality", 81.7), "weakest": ("Dividend safety", 23.8),
    }]
    latest_analysis = {"MDLZ": {
        "verdict": VERDICT_ADD, "business_view": "Neutral",
        "override_reason": "Fit penalty double-counts the sector cap",
    }}

    text, _title, _bold, _colored = render_analyst_text(analyses, latest_analysis)

    assert "Overridden from the computed Hold:" in text


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


def test_render_analyst_text_shows_non_payer_line_when_pays_dividend_false():
    """A holding with pays_dividend: False should show an explicit line
    explaining that dividend safety does not apply."""
    from tools.analyst import VERDICT_HOLD
    from tools.sync_summary_doc import render_analyst_text

    analyses = [{
        "ticker": "AMZN", "company": "Amazon.com Incoration", "is_etf": False,
        "verdict": VERDICT_HOLD, "business_view": "Neutral", "add_score": 45.0,
        "business_score": 45.0, "dividend_safety": None, "quality": 50.0,
        "value": 40.0, "fit": 45.0, "pays_dividend": False,
        "strongest": ("Quality", 50.0), "weakest": ("Valuation", 40.0),
    }]

    text, _title, _bold, _colored = render_analyst_text(analyses, {})

    assert "Amazon.com Incoration" in text
    assert "Pays no dividend - dividend safety does not apply." in text


def test_render_analyst_text_hides_non_payer_line_for_dividend_payers():
    """A holding with pays_dividend: True should NOT show the non-payer line."""
    from tools.analyst import VERDICT_HOLD
    from tools.sync_summary_doc import render_analyst_text

    analyses = [{
        "ticker": "ABT", "company": "Abbott Laboratories", "is_etf": False,
        "verdict": VERDICT_HOLD, "business_view": "Neutral", "add_score": 65.0,
        "business_score": 65.0, "dividend_safety": 75.0, "quality": 70.0,
        "value": 60.0, "fit": 60.0, "pays_dividend": True,
        "strongest": ("Quality", 70.0), "weakest": ("Valuation", 60.0),
    }]

    text, _title, _bold, _colored = render_analyst_text(analyses, {})

    assert "Abbott Laboratories" in text
    assert "Pays no dividend" not in text


def test_render_analyst_text_backward_compatible_missing_pays_dividend_key():
    """A holding without the pays_dividend key (older data) should default to
    True and NOT show the non-payer line."""
    from tools.analyst import VERDICT_HOLD
    from tools.sync_summary_doc import render_analyst_text

    analyses = [{
        "ticker": "XOM", "company": "Exxon Mobil", "is_etf": False,
        "verdict": VERDICT_HOLD, "business_view": "Neutral", "add_score": 60.0,
        "business_score": 60.0, "dividend_safety": 70.0, "quality": 65.0,
        "value": 55.0, "fit": 50.0,
        # Note: no "pays_dividend" key — simulating older analysis data
        "strongest": ("Quality", 65.0), "weakest": ("Portfolio fit", 50.0),
    }]

    text, _title, _bold, _colored = render_analyst_text(analyses, {})

    assert "Exxon Mobil" in text
    assert "Pays no dividend" not in text


def test_render_analyst_text_etf_takes_precedence_over_non_payer():
    """When a holding is both an ETF and a non-payer, the ETF line takes
    precedence because it already explains why dividend-safety doesn't apply."""
    from tools.analyst import VERDICT_HOLD
    from tools.sync_summary_doc import render_analyst_text

    analyses = [{
        "ticker": "VGRO", "company": "Vanguard Growth ETF", "is_etf": True,
        "verdict": VERDICT_HOLD, "business_view": "Neutral", "add_score": 70.0,
        "business_score": 70.0, "dividend_safety": None, "quality": None,
        "value": 75.0, "fit": 65.0, "pays_dividend": False,
        "strongest": ("Valuation", 75.0), "weakest": ("Portfolio fit", 65.0),
    }]

    text, _title, _bold, _colored = render_analyst_text(analyses, {})

    assert "Vanguard Growth ETF" in text
    assert "ETF: dividend-safety and quality scores do not apply" in text
    assert "Pays no dividend" not in text  # ETF line takes precedence


def test_render_next_euro_text_lists_ranked_holdings():
    from tools.analyst import VERDICT_ADD
    from tools.sync_summary_doc import render_next_euro_text

    analyses = [
        {"ticker": "BAC", "company": "Bank of America", "add_score": 72.0},
        {"ticker": "MCD", "company": "McDonald's", "add_score": 55.0},
    ]
    ranked = [
        {"rank": 1, "ticker": "BAC", "company": "Bank of America", "add_score": 72.0, "verdict": VERDICT_ADD,
         "strongest": ("Quality", 80.0), "weakest": ("Portfolio fit", 50.0)},
        {"rank": 2, "ticker": "MCD", "company": "McDonald's", "add_score": 55.0, "verdict": "Hold",
         "strongest": ("Dividend safety", 70.0), "weakest": ("Valuation", 40.0)},
    ]

    text, title_range, bold_ranges = render_next_euro_text(analyses, ranked)

    assert text.startswith("Where Your Next Euro Goes")
    assert "1. Bank of America (BAC)" in text
    assert "2. McDonald's (MCD)" in text
    assert "72" in text
    assert title_range == (0, len("Where Your Next Euro Goes"))
    assert bold_ranges
    assert "Not ranked" not in text  # everything in `analyses` made it into `ranked`


def test_render_next_euro_text_with_nothing_rankable():
    from tools.sync_summary_doc import render_next_euro_text

    text, _title, _bold = render_next_euro_text([], [])

    assert "not enough data" in text.lower()


def test_render_next_euro_text_lists_unrankable_holdings_under_the_ranking():
    """Spec §4: insufficient-data holdings are excluded from the ranking AND
    reported under it, so the owner sees why a holding he owns is missing."""
    from tools.sync_summary_doc import render_next_euro_text

    analyses = [
        {"ticker": "BAC", "company": "Bank of America", "add_score": 72.0},
        {"ticker": "NEW", "company": "New Co", "add_score": None},
    ]
    ranked = [
        {"rank": 1, "ticker": "BAC", "company": "Bank of America", "add_score": 72.0, "verdict": "Add",
         "strongest": ("Quality", 80.0), "weakest": ("Portfolio fit", 50.0)},
    ]

    text, _title, _bold = render_next_euro_text(analyses, ranked)

    assert "Not ranked" in text and "insufficient data" in text.lower()
    assert "New Co (NEW)" in text
    assert "Bank of America" in text.split("Not ranked", 1)[0]  # ranked entries stay above the unranked block
