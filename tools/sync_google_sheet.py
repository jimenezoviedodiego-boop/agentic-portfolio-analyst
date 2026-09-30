import gspread
from gspread.http_client import BackOffHTTPClient

from tools.allocation import compute_allocation
from tools.analyst import (
    ANALYST_LEGEND_SECTIONS,
    VERDICT_ADD,
    VERDICT_STOP,
    analyze_portfolio,
    rank_next_euro,
)
from tools.fetch_fundamentals import latest_fundamentals_snapshot
from tools.fetch_news import news_jsonl_path
from tools.fetch_prices import price_csv_path
from tools.google_auth import get_credentials
from tools.portfolio_lib import latest_by_date, load_csv_rows, load_jsonl_rows, load_portfolio, load_yaml_list
from tools.append_analysis import analysis_yaml_path
from tools.record_snapshot import latest_history_by_ticker
from tools.scoring import (
    DELTA_DOWN_COLOR,
    DELTA_UP_COLOR,
    LEGEND_SECTIONS,
    SCORE_FIELDS,
    STATUS_BANDS,
    STATUS_COLORS,
    compute_top_picks,
    render_bar,
    to_float,
)
from tools.technicals import TECHNICAL_LEGEND_SECTIONS, compute_indicators, latest_signals
from tools.ticker_tab import (
    TAB_MIN_COLS,
    build_chart_requests,
    build_ticker_tab_rows,
    existing_chart_ids,
    hex_to_rgb_fraction as _hex_to_rgb_fraction,
    resize_target,
)

SHEET_NAME = "Portfolio Tracker"

LEGEND_TAB_NAME = "Legend"
LEGEND_HEADER = ["Term", "What it means"]

ALLOCATION_TAB_NAME = "Allocation"

ANALYST_TAB_NAME = "Analyst"

OVERVIEW_HEADER = [
    "Ticker", "Company", "Shares", "Price (local)", "Currency",
    "Current Value (EUR)", "Avg Cost (local)", "G/P (EUR)", "G/P %",
    "Rating", "Overall Score",
    "Day %", "Week %", "Month %",
]
for _key, _label, _source in SCORE_FIELDS:
    OVERVIEW_HEADER += [_label, f"{_label} Bar"]
OVERVIEW_HEADER += ["RSI", "MACD", "Konkorde"]
OVERVIEW_HEADER += ["Verdict", "Confidence"]
OVERVIEW_HEADER += ["P/E", "Div Yield", "Last Updated"]

DELTA_COLUMNS = ["Day %", "Week %", "Month %"]
SCORE_COLUMNS = [label for _k, label, _s in SCORE_FIELDS]
RATING_COLUMN = "Rating"
OVERALL_SCORE_COLUMN = "Overall Score"


def _column_letter(index: int) -> str:
    """0-indexed column number -> spreadsheet column letter (A, B, ..., Z, AA, ...)."""
    index += 1
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def build_overview_rows(holdings: list[dict], latest_history: dict[str, dict], latest_fundamentals: dict[str, dict], latest_analysis: dict[str, dict], latest_technicals: dict[str, dict] | None = None, latest_verdicts: dict[str, dict] | None = None) -> list[list]:
    # Reuses the same ranking logic as the Doc's Top Picks page (unranked,
    # unfiltered here — every holding, in its original order) so "Rating"
    # here and "Overall" in the Doc are always the exact same number.
    overall_by_ticker = {
        p["ticker"]: p for p in compute_top_picks(holdings, latest_history, latest_analysis, top_n=len(holdings))
    }

    rows = [OVERVIEW_HEADER]
    for h in holdings:
        hist = latest_history.get(h["ticker"], {})
        fund = latest_fundamentals.get(h["ticker"], {})
        analysis = latest_analysis.get(h["ticker"], {})
        overall = overall_by_ticker.get(h["ticker"])

        row = [
            h["ticker"], h["company"], h["shares"],
            hist.get("price_local", ""), h["currency"],
            hist.get("value_eur", ""), h["avg_cost_local"],
            hist.get("gp_eur", ""), hist.get("gp_pct", ""),
            overall["overall_status"][1] if overall else "",
            f"{overall['overall_score']:.2f}" if overall else "",
            hist.get("day_change_pct", ""), hist.get("week_change_pct", ""), hist.get("month_change_pct", ""),
        ]

        for key, _label, source in SCORE_FIELDS:
            source_dict = hist if source == "history" else analysis
            value = source_dict.get(key, "")
            score = to_float(value)
            row.append(value)
            row.append(render_bar(score) if score is not None else "")

        tech = (latest_technicals or {}).get(h["ticker"], {})
        rsi_value = tech.get("rsi")
        row += [
            "" if rsi_value is None else round(rsi_value, 1),
            tech.get("macd_signal", ""),
            tech.get("konkorde_signal", ""),
        ]
        judgment = (latest_verdicts or {}).get(h["ticker"], {})
        row += [judgment.get("verdict", ""), judgment.get("confidence", "")]

        row += [fund.get("pe_ratio", ""), fund.get("dividend_yield", ""), hist.get("date", "")]
        rows.append(row)
    return rows


def build_legend_rows() -> list[list]:
    """Explains every column and score on the Overview tab, and where the
    data comes from — shared content with the Doc's legend page (see
    tools.scoring.LEGEND_SECTIONS). The technical-indicator rows
    (tools.technicals.TECHNICAL_LEGEND_SECTIONS) and the analyst-verdict
    rows (tools.analyst.ANALYST_LEGEND_SECTIONS) are Sheet-only — the Doc's
    legend page uses LEGEND_SECTIONS alone."""
    rows = [LEGEND_HEADER]
    for term, explanation in LEGEND_SECTIONS + TECHNICAL_LEGEND_SECTIONS + ANALYST_LEGEND_SECTIONS:
        rows.append([term, explanation])
    return rows


def build_allocation_rows(allocation: dict) -> tuple[list[list], list[int]]:
    """The Allocation tab: a totals line, then three stacked tables (by
    sector, by country, by position) separated by blank rows. Numbers are
    written as real numbers (not strings) so they sort and sum in Sheets.
    Returns (rows, header_row_indices) - the caller bolds the header rows."""
    rows: list[list] = [
        ["Total value (EUR)", round(allocation["total_eur"], 2),
         "Put in (EUR)", round(allocation["total_invested_eur"], 2)],
        [""],
    ]
    header_rows: list[int] = []

    for label, groups in (("Sector", allocation["sectors"]), ("Country", allocation["countries"])):
        header_rows.append(len(rows))
        rows.append([label, "Value (EUR)", "% of portfolio", "Holdings"])
        for g in groups:
            rows.append([g["name"], round(g["value_eur"], 2), round(g["weight_pct"], 1), ", ".join(g["tickers"])])
        rows.append([""])

    header_rows.append(len(rows))
    rows.append(["Ticker", "Company", "Sector", "Industry", "Country", "Value (EUR)", "Put in (EUR)", "% of portfolio"])
    for p in allocation["positions"]:
        rows.append([
            p["ticker"], p["company"], p["sector"], p["industry"], p["country"],
            round(p["value_eur"], 2),
            "" if p["invested_eur"] is None else round(p["invested_eur"], 2),
            round(p["weight_pct"], 1),
        ])
    return rows, header_rows


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
    ws.format(f"A1:{_column_letter(width - 1)}1", {"textFormat": {"bold": True}})


def write_allocation_tab(spreadsheet, rows: list[list], header_rows: list[int]) -> None:
    width = max(len(r) for r in rows)
    existing_titles = {ws.title for ws in spreadsheet.worksheets()}
    if ALLOCATION_TAB_NAME in existing_titles:
        ws = spreadsheet.worksheet(ALLOCATION_TAB_NAME)
        ws.clear()
        ws.resize(rows=max(len(rows), ws.row_count), cols=max(width, ws.col_count))
    else:
        ws = spreadsheet.add_worksheet(title=ALLOCATION_TAB_NAME, rows=max(len(rows), 50), cols=width, index=1)
    if ws.index != 1:
        ws.update_index(1)  # right after Legend, before Overview
    ws.update(rows)
    ws.format("A1", {"textFormat": {"bold": True}})
    for i in header_rows:
        ws.format(f"A{i + 1}:{_column_letter(width - 1)}{i + 1}", {"textFormat": {"bold": True}})


def get_or_create_spreadsheet(client, title: str = SHEET_NAME):
    try:
        return client.open(title)
    except gspread.SpreadsheetNotFound:
        return client.create(title)


def clear_conditional_formats(spreadsheet, sheet_id: int) -> None:
    """Remove all existing conditional format rules on a sheet, so re-running
    the sync doesn't pile up duplicate rules on every invocation."""
    metadata = spreadsheet.fetch_sheet_metadata()
    for sheet in metadata["sheets"]:
        if sheet["properties"]["sheetId"] != sheet_id:
            continue
        existing = sheet.get("conditionalFormats", [])
        if not existing:
            return
        requests = [
            {"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": i}}
            for i in reversed(range(len(existing)))
        ]
        spreadsheet.batch_update({"requests": requests})
        return


def _delta_format_requests(sheet_id: int, col_index: int, row_count: int) -> list[dict]:
    value_range = {
        "sheetId": sheet_id,
        "startRowIndex": 1, "endRowIndex": row_count,
        "startColumnIndex": col_index, "endColumnIndex": col_index + 1,
    }
    return [
        {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [value_range],
                    "booleanRule": {
                        "condition": {"type": "NUMBER_GREATER", "values": [{"userEnteredValue": "0"}]},
                        "format": {"textFormat": {"foregroundColor": _hex_to_rgb_fraction(DELTA_UP_COLOR), "bold": True}},
                    },
                },
                "index": 0,
            }
        },
        {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [value_range],
                    "booleanRule": {
                        "condition": {"type": "NUMBER_LESS", "values": [{"userEnteredValue": "0"}]},
                        "format": {"textFormat": {"foregroundColor": _hex_to_rgb_fraction(DELTA_DOWN_COLOR), "bold": True}},
                    },
                },
                "index": 0,
            }
        },
    ]


def _score_format_requests(sheet_id: int, col_index: int, row_count: int) -> list[dict]:
    """One rule per status band, using mutually-exclusive CUSTOM_FORMULA
    conditions (not cascading NUMBER_GREATER_THAN_EQ thresholds) so the
    result never depends on which rule Sheets evaluates first — at most one
    band's condition can ever be true for a given cell."""
    value_range = {
        "sheetId": sheet_id,
        "startRowIndex": 1, "endRowIndex": row_count,
        "startColumnIndex": col_index, "endColumnIndex": col_index + 1,
    }
    # Anchor cell for the CUSTOM_FORMULA: Sheets treats this as a relative
    # reference and re-derives it for every row in the rule's range, the
    # same way a formula typed into row 2 and filled down would adjust.
    anchor = f"{_column_letter(col_index)}2"

    # ';' (not ',') separates AND()'s arguments — this spreadsheet's locale
    # (es_ES) uses ',' as the decimal separator, so Sheets reserves ';' for
    # function-argument separation, confirmed against the live API (a ','
    # version was rejected with "Invalid ConditionValue... for ConditionType:
    # CUSTOM_FORMULA").
    band_formulas = [
        ("good", f"={anchor}>=75"),
        ("warning", f"=AND({anchor}>=50;{anchor}<75)"),
        ("serious", f"=AND({anchor}>=25;{anchor}<50)"),
        ("critical", f"={anchor}<25"),
    ]

    requests = []
    for status_key, formula in band_formulas:
        requests.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [value_range],
                    "booleanRule": {
                        "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": formula}]},
                        "format": {
                            "backgroundColor": _hex_to_rgb_fraction(STATUS_COLORS[status_key]),
                            "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1}, "bold": True},
                        },
                    },
                },
                "index": 0,
            }
        })
    return requests


def _rating_format_requests(sheet_id: int, col_index: int, row_count: int) -> list[dict]:
    """Colors the text "Rating" column (Strong Buy/Buy/Hold/Sell) by exact
    match — unlike the numeric score columns, no formula parsing/locale risk
    here, just a straight text comparison."""
    value_range = {
        "sheetId": sheet_id,
        "startRowIndex": 1, "endRowIndex": row_count,
        "startColumnIndex": col_index, "endColumnIndex": col_index + 1,
    }
    requests = []
    for _threshold, status_key, label in STATUS_BANDS:
        requests.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [value_range],
                    "booleanRule": {
                        "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": label}]},
                        "format": {
                            "backgroundColor": _hex_to_rgb_fraction(STATUS_COLORS[status_key]),
                            "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1}, "bold": True},
                        },
                    },
                },
                "index": 0,
            }
        })
    return requests


def _column_range(sheet_id: int, col_index: int, row_count: int) -> dict:
    return {
        "sheetId": sheet_id,
        "startRowIndex": 1, "endRowIndex": row_count,
        "startColumnIndex": col_index, "endColumnIndex": col_index + 1,
    }


def _text_color_rule(value_range: dict, condition_type: str, value: str, hex_color: str) -> dict:
    return {
        "addConditionalFormatRule": {
            "rule": {
                "ranges": [value_range],
                "booleanRule": {
                    "condition": {"type": condition_type, "values": [{"userEnteredValue": value}]},
                    "format": {"textFormat": {"foregroundColor": _hex_to_rgb_fraction(hex_color), "bold": True}},
                },
            },
            "index": 0,
        }
    }


def _rsi_format_requests(sheet_id: int, col_index: int, row_count: int) -> list[dict]:
    """RSI > 70 red (overbought), < 30 green (oversold); the two conditions
    can never both hold, so rule order doesn't matter."""
    value_range = _column_range(sheet_id, col_index, row_count)
    return [
        _text_color_rule(value_range, "NUMBER_GREATER", "70", DELTA_DOWN_COLOR),
        _text_color_rule(value_range, "NUMBER_LESS", "30", DELTA_UP_COLOR),
    ]


def _signal_text_format_requests(sheet_id: int, col_index: int, row_count: int, positive_prefix: str, negative_prefix: str) -> list[dict]:
    """Green/red text for the MACD ("Bullish…"/"Bearish…") and Konkorde
    ("Sharks buying"/"Sharks selling") signal columns."""
    value_range = _column_range(sheet_id, col_index, row_count)
    return [
        _text_color_rule(value_range, "TEXT_STARTS_WITH", positive_prefix, DELTA_UP_COLOR),
        _text_color_rule(value_range, "TEXT_STARTS_WITH", negative_prefix, DELTA_DOWN_COLOR),
    ]


def _monospace_bar_column_request(sheet_id: int, col_index: int, row_count: int) -> dict:
    """The bar columns hold plain Unicode block-character text (not a
    formula, to avoid locale-dependent formula syntax) — a monospace font
    keeps the filled/empty blocks aligned into a visual bar."""
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1, "endRowIndex": row_count,
                "startColumnIndex": col_index, "endColumnIndex": col_index + 1,
            },
            "cell": {"userEnteredFormat": {"textFormat": {"fontFamily": "Courier New"}}},
            "fields": "userEnteredFormat.textFormat.fontFamily",
        }
    }


def apply_overview_formatting(spreadsheet, worksheet, row_count: int) -> None:
    """Colors the Rating and Overall Score columns, the Day/Week/Month
    change columns (green up, red down), the 4 dimension score columns
    (Sell/Hold/Buy/Strong Buy background), sets a monospace font on the
    4 bar columns so their blocks stay aligned, plus the RSI (overbought
    red / oversold green) and MACD / Konkorde signal columns (green/red
    text)."""
    sheet_id = worksheet.id
    clear_conditional_formats(spreadsheet, sheet_id)

    requests = []
    requests += _rating_format_requests(sheet_id, OVERVIEW_HEADER.index(RATING_COLUMN), row_count)
    requests += _score_format_requests(sheet_id, OVERVIEW_HEADER.index(OVERALL_SCORE_COLUMN), row_count)
    for label in DELTA_COLUMNS:
        col_index = OVERVIEW_HEADER.index(label)
        requests += _delta_format_requests(sheet_id, col_index, row_count)
    for label in SCORE_COLUMNS:
        col_index = OVERVIEW_HEADER.index(label)
        requests += _score_format_requests(sheet_id, col_index, row_count)
        requests.append(_monospace_bar_column_request(sheet_id, OVERVIEW_HEADER.index(f"{label} Bar"), row_count))

    requests += _rsi_format_requests(sheet_id, OVERVIEW_HEADER.index("RSI"), row_count)
    requests += _signal_text_format_requests(sheet_id, OVERVIEW_HEADER.index("MACD"), row_count, "Bullish", "Bearish")
    requests += _signal_text_format_requests(sheet_id, OVERVIEW_HEADER.index("Konkorde"), row_count, "Sharks buying", "Sharks selling")

    requests += _signal_text_format_requests(
        sheet_id, OVERVIEW_HEADER.index("Verdict"), row_count, VERDICT_ADD, VERDICT_STOP
    )

    if requests:
        spreadsheet.batch_update({"requests": requests})


def write_legend_tab(spreadsheet, legend_rows: list[list]) -> None:
    existing_titles = {ws.title for ws in spreadsheet.worksheets()}
    if LEGEND_TAB_NAME in existing_titles:
        ws = spreadsheet.worksheet(LEGEND_TAB_NAME)
        ws.clear()
        ws.resize(rows=max(len(legend_rows), ws.row_count), cols=max(len(LEGEND_HEADER), ws.col_count))
    else:
        ws = spreadsheet.add_worksheet(title=LEGEND_TAB_NAME, rows=max(len(legend_rows), 20), cols=2, index=0)
    if ws.index != 0:
        ws.update_index(0)  # keep it the first tab, matching the "read this first" role of the Doc's legend page
    ws.update(legend_rows)
    ws.format("A1:B1", {"textFormat": {"bold": True}})
    ws.format(f"B2:B{len(legend_rows)}", {"wrapStrategy": "WRAP"})


def _overview_worksheet_title_from(titles: list[str]) -> str | None:
    """Pure selection logic for _get_or_prepare_overview_worksheet: which
    existing tab (if any) should be repurposed as Overview on a first-ever
    run. Returns None when a tab named "Overview" already exists (nothing to
    repurpose) or when every tab is one of the pinned tabs (Legend,
    Allocation, Analyst) with no leftover default tab to take over."""
    if "Overview" in titles:
        return None
    for title in titles:
        if title not in (LEGEND_TAB_NAME, ALLOCATION_TAB_NAME, ANALYST_TAB_NAME):
            return title
    return None


def _get_or_prepare_overview_worksheet(spreadsheet):
    """Finds the "Overview" tab by name, not by position — spreadsheet.sheet1
    (index 0) is not reliable here since the Legend tab is kept pinned to
    index 0, which would otherwise make sheet1 resolve to Legend instead."""
    worksheets = spreadsheet.worksheets()
    for ws in worksheets:
        if ws.title == "Overview":
            return ws
    # First-ever run: repurpose whichever default tab isn't one of the
    # pinned tabs (Legend/Allocation/Analyst) we just wrote.
    title_to_repurpose = _overview_worksheet_title_from([ws.title for ws in worksheets])
    if title_to_repurpose is not None:
        for ws in worksheets:
            if ws.title == title_to_repurpose:
                return ws
    return spreadsheet.add_worksheet(title="Overview", rows=100, cols=len(OVERVIEW_HEADER))


def write_sheet(spreadsheet, overview_rows: list[list], ticker_tabs: dict[str, list[list]], allocation: dict, analyst_rows: list[list]) -> None:
    write_legend_tab(spreadsheet, build_legend_rows())
    write_allocation_tab(spreadsheet, *build_allocation_rows(allocation))
    write_analyst_tab(spreadsheet, analyst_rows)

    overview_ws = _get_or_prepare_overview_worksheet(spreadsheet)
    overview_ws.update_title("Overview")
    overview_ws.clear()
    # A brand-new spreadsheet's default tab is 1000x26; OVERVIEW_HEADER is
    # now 28 columns (technical columns pushed it past 25), so a first-ever
    # run must grow the grid before update() or the write is capped/rejected
    # at column AB. Matches the pattern used for Legend/Allocation/ticker tabs.
    overview_ws.resize(rows=max(len(overview_rows), overview_ws.row_count), cols=max(len(OVERVIEW_HEADER), overview_ws.col_count))
    overview_ws.update(overview_rows)
    overview_ws.freeze(rows=1, cols=2)
    apply_overview_formatting(spreadsheet, overview_ws, len(overview_rows))

    existing_titles = {ws.title for ws in spreadsheet.worksheets()}
    # One metadata read for the whole sync (chart IDs per tab), rather than
    # one per tab — keeps us well inside the Sheets per-minute quota.
    metadata = spreadsheet.fetch_sheet_metadata()
    for ticker, rows in ticker_tabs.items():
        if ticker in existing_titles:
            ws = spreadsheet.worksheet(ticker)
            ws.clear()
            # ws.clear() does not resize the grid, so a tab whose price
            # history has grown past its current row count would silently
            # lose an update() call without this — resize to at least fit.
            # Columns: the indicator layout plus the charts' anchor column.
            # Only fire the write when the grid doesn't already fit — most
            # syncs don't grow past the existing row/col count, and this
            # avoids 15 needless resize() calls against the ~60/min quota.
            target = resize_target(ws.row_count, ws.col_count, len(rows))
            if target is not None:
                ws.resize(rows=target[0], cols=target[1])
        else:
            ws = spreadsheet.add_worksheet(title=ticker, rows=max(len(rows), 100), cols=TAB_MIN_COLS)
        ws.update(rows)
        spreadsheet.batch_update({"requests": build_chart_requests(ws.id, len(rows), existing_chart_ids(metadata, ws.id))})


def main():
    holdings = load_portfolio()
    latest_history = latest_history_by_ticker()
    latest_fundamentals = {h["ticker"]: (latest_fundamentals_snapshot(h["ticker"]) or {}) for h in holdings}
    latest_analysis = {
        h["ticker"]: (latest_by_date(load_yaml_list(analysis_yaml_path(h["ticker"]), "entries")) or {})
        for h in holdings
    }

    ticker_tabs = {}
    latest_technicals = {}
    for h in holdings:
        price_rows = load_csv_rows(price_csv_path(h["ticker"]))
        news_entries = load_jsonl_rows(news_jsonl_path(h["ticker"]))
        indicators = compute_indicators(price_rows)
        latest_technicals[h["ticker"]] = latest_signals(indicators)
        if price_rows:
            ticker_tabs[h["ticker"]] = build_ticker_tab_rows(price_rows, news_entries, indicators)

    allocation = compute_allocation(holdings, latest_history, latest_fundamentals)
    analyses = analyze_portfolio(holdings, latest_fundamentals, latest_history, allocation)
    ranked = rank_next_euro(analyses)
    latest_verdicts = {
        t: {"verdict": a.get("verdict", ""), "confidence": a.get("confidence", "")}
        for t, a in latest_analysis.items()
    }

    overview_rows = build_overview_rows(holdings, latest_history, latest_fundamentals, latest_analysis, latest_technicals, latest_verdicts)

    # BackOffHTTPClient retries 429 "quota exceeded" responses with
    # exponential backoff: 15 ticker tabs x (clear, resize, update, charts)
    # plus the other tabs is close to Sheets' ~60 writes/minute limit.
    client = gspread.authorize(get_credentials(), http_client=BackOffHTTPClient)
    spreadsheet = get_or_create_spreadsheet(client)
    write_sheet(spreadsheet, overview_rows, ticker_tabs, allocation, build_analyst_rows(ranked, analyses))
    print(f"Synced {len(holdings)} holdings to Google Sheet: {spreadsheet.url}")


if __name__ == "__main__":
    main()
