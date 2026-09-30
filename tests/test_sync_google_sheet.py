from tools.sync_google_sheet import (
    LEGEND_HEADER,
    OVERVIEW_HEADER,
    _column_letter,
    _delta_format_requests,
    _overview_worksheet_title_from,
    _rating_format_requests,
    _rsi_format_requests,
    _score_format_requests,
    _signal_text_format_requests,
    build_analyst_rows,
    build_legend_rows,
    build_overview_rows,
)


def test_build_legend_rows_covers_every_documented_term():
    from tools.analyst import ANALYST_LEGEND_SECTIONS
    from tools.scoring import LEGEND_SECTIONS
    from tools.technicals import TECHNICAL_LEGEND_SECTIONS

    rows = build_legend_rows()

    assert rows[0] == LEGEND_HEADER
    expected = LEGEND_SECTIONS + TECHNICAL_LEGEND_SECTIONS + ANALYST_LEGEND_SECTIONS
    assert len(rows) == len(expected) + 1
    assert [row[0] for row in rows[1:]] == [term for term, _explanation in expected]


def test_column_letter_conversion():
    assert _column_letter(0) == "A"
    assert _column_letter(1) == "B"
    assert _column_letter(25) == "Z"
    assert _column_letter(26) == "AA"
    assert _column_letter(27) == "AB"
    assert _column_letter(51) == "AZ"
    assert _column_letter(52) == "BA"


def test_build_overview_rows_includes_header_and_one_row_per_holding():
    holdings = [
        {"ticker": "HON", "company": "Honeywell International", "shares": 10, "currency": "USD", "avg_cost_local": 120.50, "is_etf": False},
    ]
    latest_history = {"HON": {"price_local": "163.90", "value_eur": "1500.00", "gp_eur": "250.00", "gp_pct": "20.00", "date": "2026-09-16"}}
    latest_fundamentals = {"HON": {"pe_ratio": 22.4, "dividend_yield": 0.028}}
    latest_analysis = {}

    rows = build_overview_rows(holdings, latest_history, latest_fundamentals, latest_analysis)

    assert rows[0][0] == "Ticker"
    assert rows[0] == OVERVIEW_HEADER
    assert rows[1][0] == "HON"
    assert rows[1][5] == "1500.00"  # Value (EUR) column unchanged by the new columns


def test_build_overview_rows_includes_deltas_and_score_bars():
    holdings = [
        {"ticker": "HON", "company": "Honeywell International", "shares": 10, "currency": "USD", "avg_cost_local": 120.50, "is_etf": False},
    ]
    latest_history = {
        "HON": {
            "price_local": "163.90", "value_eur": "1500.00", "gp_eur": "250.00", "gp_pct": "20.00", "date": "2026-09-16",
            "day_change_pct": "1.50", "week_change_pct": "-2.30", "month_change_pct": "5.00",
            "valuation_score": "62.50", "momentum_score": "70.00", "financial_health_score": "80.00",
        }
    }
    latest_fundamentals = {"HON": {"pe_ratio": 22.4, "dividend_yield": 0.028}}
    latest_analysis = {"HON": {"news_sentiment_score": 65}}

    rows = build_overview_rows(holdings, latest_history, latest_fundamentals, latest_analysis)
    row = rows[1]
    by_header = dict(zip(OVERVIEW_HEADER, row))

    assert by_header["Day %"] == "1.50"
    assert by_header["Week %"] == "-2.30"
    assert by_header["Month %"] == "5.00"
    assert by_header["Valuation"] == "62.50"
    assert by_header["News Sentiment"] == 65
    # score bars are plain Unicode block-character text (not a formula —
    # avoids locale-dependent Sheets formula syntax, e.g. es_ES uses ';'
    # as the argument separator and '\' inside array literals)
    assert by_header["Valuation Bar"] == "█" * 6 + "░" * 4  # 62.5 -> 6/10 filled
    assert by_header["News Sentiment Bar"] == "█" * 6 + "░" * 4  # 65 -> round(6.5)=6 (round-half-to-even)


def test_build_overview_rows_includes_rating_and_overall_score():
    holdings = [
        {"ticker": "HON", "company": "Honeywell International", "shares": 10, "currency": "USD", "avg_cost_local": 120.50, "is_etf": False},
        {"ticker": "NODATA", "company": "No Data Co", "shares": 1, "currency": "USD", "avg_cost_local": 1.0, "is_etf": False},
    ]
    latest_history = {
        "HON": {
            "value_eur": "1500.00", "gp_eur": "250.00", "gp_pct": "20.00",
            "valuation_score": "90.00", "momentum_score": "90.00", "financial_health_score": "90.00",
        }
    }
    latest_analysis = {"HON": {"news_sentiment_score": 90}}

    rows = build_overview_rows(holdings, latest_history, {}, latest_analysis)
    mmm_row = dict(zip(OVERVIEW_HEADER, rows[1]))
    nodata_row = dict(zip(OVERVIEW_HEADER, rows[2]))

    assert mmm_row["Rating"] == "Strong Buy"
    assert mmm_row["Overall Score"] == "90.00"
    # a holding with no scores at all gets blanks, not a fabricated rating
    assert nodata_row["Rating"] == ""
    assert nodata_row["Overall Score"] == ""


def test_rating_format_requests_one_rule_per_band_matched_by_exact_text():
    requests = _rating_format_requests(sheet_id=123, col_index=9, row_count=10)
    assert len(requests) == 4
    labels = {
        r["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"]["values"][0]["userEnteredValue"]
        for r in requests
    }
    assert labels == {"Strong Buy", "Buy", "Hold", "Sell"}
    for r in requests:
        assert r["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"]["type"] == "TEXT_EQ"


def test_build_overview_rows_blank_score_leaves_bar_blank():
    holdings = [
        {"ticker": "KD", "company": "Kyndryl Holdings", "shares": 3, "currency": "USD", "avg_cost_local": 0.0, "is_etf": False},
    ]
    latest_history = {"KD": {"price_local": "90.44", "value_eur": "235.07", "gp_eur": "", "gp_pct": "", "date": "2026-09-16"}}

    rows = build_overview_rows(holdings, latest_history, {}, {})
    row = rows[1]
    by_header = dict(zip(OVERVIEW_HEADER, row))

    assert by_header["Valuation"] == ""
    assert by_header["Valuation Bar"] == ""


def test_score_format_requests_bands_are_mutually_exclusive():
    # A prior version used cascading NUMBER_GREATER_THAN_EQ thresholds whose
    # correctness silently depended on Sheets' rule-evaluation order (which
    # this project can't verify without live credentials). Each band's
    # CUSTOM_FORMULA condition must be independently self-contained so at
    # most one can ever be true for a given score, regardless of rule order.
    requests = _score_format_requests(sheet_id=123, col_index=5, row_count=10)
    assert len(requests) == 4

    def score_matches(formula: str, score: float) -> bool:
        # Translate the Sheets formula (anchored at F2) into a Python check
        # against a substitute score, mirroring what Sheets would evaluate.
        # Uses ';' as AND()'s argument separator, not ',' — confirmed against
        # the live Sheets API, which rejects ',' for this account's locale
        # (es_ES, where ',' is the decimal separator).
        expr = formula.lstrip("=").replace("F2", str(score))
        expr = expr.replace("AND(", "(").replace(";", " and ")
        return eval(expr)  # noqa: S307 — trusted, test-authored formula text only

    formulas = [r["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"]["values"][0]["userEnteredValue"] for r in requests]
    for probe_score in [0, 24.9, 25, 49.9, 50, 74.9, 75, 100]:
        matches = [f for f in formulas if score_matches(f, probe_score)]
        assert len(matches) == 1, f"score {probe_score} matched {len(matches)} bands, expected exactly 1"


def test_delta_format_requests_up_and_down_are_mutually_exclusive():
    requests = _delta_format_requests(sheet_id=123, col_index=9, row_count=10)
    assert len(requests) == 2
    conditions = [r["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"]["type"] for r in requests]
    assert conditions == ["NUMBER_GREATER", "NUMBER_LESS"]


def test_build_allocation_rows_has_sector_country_and_position_tables():
    from tools.allocation import compute_allocation
    from tools.sync_google_sheet import build_allocation_rows

    holdings = [{"ticker": "AAA", "company": "Alpha"}, {"ticker": "BBB", "company": "Beta"}]
    history = {"AAA": {"value_eur": "750", "gp_eur": "250"}, "BBB": {"value_eur": "250", "gp_eur": ""}}
    fundamentals = {
        "AAA": {"quote_type": "EQUITY", "sector": "Healthcare", "country": "United States"},
        "BBB": {"quote_type": "EQUITY", "sector": "Industrials", "country": "United States"},
    }
    rows, header_rows = build_allocation_rows(compute_allocation(holdings, history, fundamentals))

    header_firsts = [rows[i][0] for i in header_rows]
    assert header_firsts == ["Sector", "Country", "Ticker"]

    sector_row = next(r for r in rows if r and r[0] == "Healthcare")
    assert sector_row[1] == 750.0 and sector_row[2] == 75.0 and "AAA" in sector_row[3]

    aaa = next(r for r in rows if r and r[0] == "AAA")
    assert aaa[1] == "Alpha" and aaa[2] == "Healthcare"
    assert 750.0 in aaa and 500.0 in aaa  # value and invested
    bbb = next(r for r in rows if r and r[0] == "BBB")
    assert "" in bbb  # unknown invested stays blank, not 0


_MMM_HOLDING = {"ticker": "HON", "company": "Honeywell International", "shares": 10, "currency": "USD", "avg_cost_local": 120.50, "is_etf": False}
_MMM_HISTORY = {"HON": {"price_local": "163.90", "value_eur": "1500.00", "gp_eur": "250.00", "gp_pct": "20.00", "date": "2026-09-16"}}


def test_overview_header_has_technical_columns_before_pe():
    i = OVERVIEW_HEADER.index("RSI")
    assert OVERVIEW_HEADER[i:i + 4] == ["RSI", "MACD", "Konkorde", "Verdict"]


def test_build_overview_rows_includes_latest_technical_signals():
    technicals = {"HON": {"rsi": 72.345, "macd_signal": "Bullish ↑ cross", "konkorde_signal": "Sharks buying"}}

    rows = build_overview_rows([_MMM_HOLDING], _MMM_HISTORY, {}, {}, technicals)

    row = dict(zip(OVERVIEW_HEADER, rows[1]))
    assert row["RSI"] == 72.3
    assert row["MACD"] == "Bullish ↑ cross"
    assert row["Konkorde"] == "Sharks buying"


def test_build_overview_rows_technicals_blank_when_missing():
    rows = build_overview_rows([_MMM_HOLDING], _MMM_HISTORY, {}, {})

    row = dict(zip(OVERVIEW_HEADER, rows[1]))
    assert row["RSI"] == "" and row["MACD"] == "" and row["Konkorde"] == ""


def test_rsi_format_requests_overbought_red_oversold_green():
    from tools.scoring import DELTA_DOWN_COLOR, DELTA_UP_COLOR
    from tools.ticker_tab import hex_to_rgb_fraction

    requests = _rsi_format_requests(sheet_id=3, col_index=5, row_count=10)
    rules = [r["addConditionalFormatRule"]["rule"]["booleanRule"] for r in requests]

    by_condition = {(b["condition"]["type"], b["condition"]["values"][0]["userEnteredValue"]): b["format"] for b in rules}
    assert by_condition[("NUMBER_GREATER", "70")]["textFormat"]["foregroundColor"] == hex_to_rgb_fraction(DELTA_DOWN_COLOR)
    assert by_condition[("NUMBER_LESS", "30")]["textFormat"]["foregroundColor"] == hex_to_rgb_fraction(DELTA_UP_COLOR)


def test_signal_text_format_requests_match_by_prefix():
    requests = _signal_text_format_requests(sheet_id=3, col_index=5, row_count=10,
                                            positive_prefix="Bullish", negative_prefix="Bearish")
    conditions = [r["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"] for r in requests]
    assert [(c["type"], c["values"][0]["userEnteredValue"]) for c in conditions] == [
        ("TEXT_STARTS_WITH", "Bullish"), ("TEXT_STARTS_WITH", "Bearish"),
    ]


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


def test_overview_worksheet_title_from_existing_overview_signals_no_repurposing():
    assert _overview_worksheet_title_from(["Legend", "Overview", "Allocation"]) is None


def test_overview_worksheet_title_from_fresh_spreadsheet_picks_default_tab_not_analyst():
    # On a brand-new spreadsheet the tab order is Legend, Allocation, Analyst,
    # then whatever Sheets named the untouched default tab — that default tab
    # is the only one that should ever be repurposed as Overview. Regression
    # test for a bug where the just-written Analyst tab got renamed to
    # Overview and cleared on a first-ever sync.
    assert _overview_worksheet_title_from(["Legend", "Allocation", "Analyst", "Sheet1"]) == "Sheet1"


def test_overview_worksheet_title_from_no_candidate_returns_none():
    assert _overview_worksheet_title_from(["Legend", "Allocation", "Analyst"]) is None
