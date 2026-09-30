from googleapiclient.discovery import build

from tools.google_auth import get_credentials
from tools.portfolio_lib import latest_by_date, load_portfolio, load_yaml_list
from tools.allocation import POSITION_LIMIT_PCT, SECTOR_LIMIT_PCT, compute_allocation
from tools.analyst import analyze_portfolio, rank_next_euro
from tools.append_analysis import analysis_yaml_path
from tools.fetch_fundamentals import latest_fundamentals_snapshot
from tools.record_snapshot import latest_history_by_ticker, previous_history_by_ticker
from tools.scoring import LEGEND_SECTIONS, SCORE_FIELDS, STATUS_COLORS, compute_top_picks, render_bar, score_status, to_float

TOP_PICKS_COUNT = 5

DOC_TITLE = "Portfolio Summary"

SCORE_LABEL_WIDTH = 15
SCORE_BAR_WIDTH = 10
MONOSPACE_FONT = "Courier New"  # guaranteed available in Docs, unlike web fonts — bar alignment depends on it

VERDICT_COLORS = {
    "Add": STATUS_COLORS["good"],
    "Hold": STATUS_COLORS["warning"],
    "Stop adding": STATUS_COLORS["critical"],
    "Insufficient data": STATUS_COLORS["serious"],
}


def previous_analysis_entry(entries: list[dict]) -> dict | None:
    """The second-most-recent analysis entry (by date) — "last run", to
    compare today's news sentiment score against. None if fewer than 2 entries."""
    sorted_entries = sorted(entries, key=lambda e: e["date"])
    return sorted_entries[-2] if len(sorted_entries) >= 2 else None


def build_summary_sections(
    holdings: list[dict],
    latest_analysis: dict[str, dict],
    latest_history: dict[str, dict],
    previous_analysis: dict[str, dict],
    previous_history: dict[str, dict],
) -> list[dict]:
    sections = []
    for h in holdings:
        analysis = latest_analysis.get(h["ticker"], {})
        hist = latest_history.get(h["ticker"], {})
        prev_analysis = previous_analysis.get(h["ticker"], {})
        prev_hist = previous_history.get(h["ticker"], {})

        score_lines = []
        scores_for_overall = []
        for key, label, source in SCORE_FIELDS:
            current = hist if source == "history" else analysis
            previous = prev_hist if source == "history" else prev_analysis
            score = to_float(current.get(key))
            previous_score = to_float(previous.get(key))
            status = score_status(score)
            score_lines.append(
                {"label": label, "score": score, "previous_score": previous_score, "status": status}
            )
            if score is not None:
                scores_for_overall.append(score)

        overall_score = sum(scores_for_overall) / len(scores_for_overall) if scores_for_overall else None

        sections.append(
            {
                "heading": f"{h['company']} ({h['ticker']})",
                "summary_line": (
                    f"Shares: {h['shares']}  |  Current Value: {hist.get('value_eur', 'n/a')} EUR  |  "
                    f"G/P: {hist.get('gp_eur', 'n/a')} EUR ({hist.get('gp_pct', 'n/a')}%)"
                ),
                "overall_status": score_status(overall_score),
                "overall_score": overall_score,
                "score_lines": score_lines,
                "status_text": analysis.get("status", "No status recorded yet."),
                "price_narrative": analysis.get("price_narrative", "No narrative recorded yet."),
                "watch": analysis.get("watch", "Nothing flagged."),
            }
        )
    return sections


def _score_line_text(line: dict) -> tuple[str, tuple[int, int]]:
    score = line["score"]
    bar = render_bar(score, SCORE_BAR_WIDTH)
    score_text = "n/a" if score is None else f"{round(score)}/100"
    last_text = ""
    if line["previous_score"] is not None and score is not None:
        last_text = f" (last: {round(line['previous_score'])})"

    text = f"{line['label']:<{SCORE_LABEL_WIDTH}}{bar} {score_text}{last_text}"
    color_start = SCORE_LABEL_WIDTH
    color_end = SCORE_LABEL_WIDTH + SCORE_BAR_WIDTH + 1 + len(score_text)
    return text, (color_start, color_end)


def render_section_text(
    section: dict,
) -> tuple[str, list[tuple[int, int, str]], tuple[int, int], list[tuple[int, int]], list[tuple[int, int]]]:
    """Renders one company section to plain text plus the styling metadata
    write_doc needs: colored_ranges (start, end, hex) for the Overall line
    and score bars, the heading's (start, end) for its paragraph style,
    monospace_ranges (start, end) for the score-bar lines, and bold_ranges
    (start, end) for the News/Fundamentals/Watch mini-labels — kept as three
    clearly separated, labeled blocks rather than one dense paragraph. All
    offsets are relative to the returned text (0-based), not the final
    document."""
    lines_text: list[str] = []
    colored_ranges: list[tuple[int, int, str]] = []
    monospace_ranges: list[tuple[int, int]] = []
    bold_ranges: list[tuple[int, int]] = []
    offset = 0

    def add_line(text: str) -> tuple[int, int]:
        nonlocal offset
        start = offset
        lines_text.append(text)
        end = start + len(text)
        offset = end + 1  # +1 reserves the '\n' the eventual join() will insert
        return start, end

    def add_labeled_block(label: str, body: str) -> None:
        start, end = add_line(label)
        bold_ranges.append((start, end))
        add_line(body)

    heading_range = add_line(section["heading"])

    add_line(section["summary_line"])

    if section["overall_status"]:
        key, label = section["overall_status"]
        prefix = "Overall: "
        line_text = f"{prefix}{label} ({round(section['overall_score'])}/100)"
        start, end = add_line(line_text)
        colored_ranges.append((start + len(prefix), end, STATUS_COLORS[key]))
    else:
        add_line("Overall: No data yet.")

    for line in section["score_lines"]:
        text, (cs, ce) = _score_line_text(line)
        start, end = add_line(text)
        monospace_ranges.append((start, end))
        if line["status"]:
            colored_ranges.append((start + cs, start + ce, STATUS_COLORS[line["status"][0]]))

    add_line("")
    add_labeled_block("News", section["price_narrative"])
    add_line("")
    add_labeled_block("Fundamentals", section["status_text"])
    add_line("")
    add_labeled_block("Watch", section["watch"])

    return "\n".join(lines_text), colored_ranges, heading_range, monospace_ranges, bold_ranges


def render_legend_text() -> tuple[str, list[tuple[int, int]], tuple[int, int]]:
    """Renders the static "How to Read This Report" page inserted before the
    per-company sections, explaining every figure/score and where the data
    comes from (see tools.scoring.LEGEND_SECTIONS, the single source of
    truth shared with the Sheet's Legend tab). Returns (text, bold_ranges,
    title_range) — bold_ranges includes the title; the caller distinguishes
    the title for HEADING_1 styling by identity with title_range."""
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

    title_range = add_line("How to Read This Report")
    bold_ranges.append(title_range)
    add_line(
        "This page explains what each figure and score means, and where the "
        "underlying data comes from. Everything below is refreshed each "
        "time the portfolio is updated."
    )
    add_line("")

    for term, explanation in LEGEND_SECTIONS:
        start, end = add_line(term)
        bold_ranges.append((start, end))
        add_line(explanation)
        add_line("")

    return "\n".join(lines_text), bold_ranges, title_range


ALLOCATION_LABEL_WIDTH = 20
POSITION_LABEL_WIDTH = 9


def _allocation_line(label: str, label_width: int, weight: float, max_weight: float, value: float, tail: str) -> str:
    # Bars are scaled to the largest group on the page (not to 100%), so
    # 5% and 15% positions are still visibly different lengths.
    bar = render_bar(weight / max_weight * 100 if max_weight else 0, SCORE_BAR_WIDTH)
    return f"{label:<{label_width}}{bar} {weight:5.1f}%  EUR {value:>7,.0f}  {tail}"


def render_allocation_text(
    allocation: dict,
) -> tuple[str, tuple[int, int], list[tuple[int, int]], list[tuple[int, int]]]:
    """Renders the "Portfolio Allocation" page - the first thing in the Doc -
    showing how the portfolio's current value splits by sector, country and
    position, plus concentration flags (see tools.allocation). Returns (text,
    title_range, bold_ranges, monospace_ranges); bold_ranges excludes the
    title."""
    lines_text: list[str] = []
    bold_ranges: list[tuple[int, int]] = []
    monospace_ranges: list[tuple[int, int]] = []
    offset = 0

    def add_line(text: str) -> tuple[int, int]:
        nonlocal offset
        start = offset
        lines_text.append(text)
        end = start + len(text)
        offset = end + 1
        return start, end

    def add_heading(text: str) -> None:
        bold_ranges.append(add_line(text))

    def add_mono(text: str) -> None:
        monospace_ranges.append(add_line(text))

    title_range = add_line("Portfolio Allocation")
    total = allocation["total_eur"]
    invested = allocation["total_invested_eur"]
    add_line(
        f"Total value: EUR {total:,.0f} across {len(allocation['positions'])} holdings. "
        f"You put in about EUR {invested:,.0f} (holdings with a known cost basis); "
        "the rest is growth. A position's weight grows when it outperforms, even "
        "if you never added money to it - compare its value with what you put in."
    )
    add_line("")

    for heading, groups in (("By sector", allocation["sectors"]), ("By country", allocation["countries"])):
        add_heading(heading)
        max_weight = max((g["weight_pct"] for g in groups), default=0)
        for g in groups:
            add_mono(_allocation_line(g["name"], ALLOCATION_LABEL_WIDTH, g["weight_pct"], max_weight,
                                      g["value_eur"], ", ".join(g["tickers"])))
        add_line("")

    add_heading("By position")
    positions = allocation["positions"]
    max_weight = max((p["weight_pct"] for p in positions), default=0)
    for p in positions:
        put_in = "unknown" if p["invested_eur"] is None else f"EUR {p['invested_eur']:,.0f}"
        add_mono(_allocation_line(p["ticker"], POSITION_LABEL_WIDTH, p["weight_pct"], max_weight, p["value_eur"],
                                  f"{p['company']} - {p['sector']} - put in: {put_in}"))
    add_line("")

    add_heading("Concentration check")
    if allocation["flags"]:
        for flag in allocation["flags"]:
            add_line(f"- {flag}")
    else:
        add_line(f"No stock above {POSITION_LIMIT_PCT:.0f}% and no sector above {SECTOR_LIMIT_PCT:.0f}%.")
    add_line(
        f"These are common rules of thumb ({POSITION_LIMIT_PCT:.0f}% per stock, {SECTOR_LIMIT_PCT:.0f}% "
        "per sector), not hard limits. The ETF is diversified by construction, so it is never flagged."
    )

    return "\n".join(lines_text), title_range, bold_ranges, monospace_ranges


def render_top_picks_text(
    picks: list[dict],
) -> tuple[str, list[tuple[int, int, str]], tuple[int, int], list[tuple[int, int]]]:
    """Renders the "Top Picks" page — right after the Allocation page — ranking
    holdings by Overall score with a concrete one-line reason each (their
    single highest-scoring dimension), so the answer to "should I add more
    to these" is visible before anything else. Returns (text, colored_ranges,
    title_range, bold_ranges)."""
    lines_text: list[str] = []
    colored_ranges: list[tuple[int, int, str]] = []
    bold_ranges: list[tuple[int, int]] = []
    offset = 0

    def add_line(text: str) -> tuple[int, int]:
        nonlocal offset
        start = offset
        lines_text.append(text)
        end = start + len(text)
        offset = end + 1
        return start, end

    title_range = add_line("Top Picks")
    bold_ranges.append(title_range)
    add_line(
        f"The {len(picks)} highest-rated holdings right now, ranked by Overall "
        "score. This reads today's numbers - it is not investment advice, so "
        "check each holding's full section before acting on it."
    )
    add_line("")

    if not picks:
        add_line("No holdings have enough data yet to rank.")

    for i, pick in enumerate(picks, start=1):
        key, label = pick["overall_status"]
        rank_prefix = f"{i}. {pick['company']} ({pick['ticker']}) - "
        rating_text = f"{label} ({round(pick['overall_score'])}/100)"
        start, end = add_line(rank_prefix + rating_text)
        colored_ranges.append((start + len(rank_prefix), end, STATUS_COLORS[key]))

        add_line(f"   Strongest signal: {pick['top_dimension_label']} ({round(pick['top_dimension_score'])}/100).")
        add_line("")

    return "\n".join(lines_text), colored_ranges, title_range, bold_ranges


def _score_text(value) -> str:
    return "n/a" if value is None else str(round(value))


def render_analyst_text(
    analyses: list[dict], latest_analysis: dict
) -> tuple[str, tuple[int, int], list[tuple[int, int]], list[tuple[int, int, str]]]:
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
        # Only the verdict portion is coloured — verdict and business view are
        # deliberately independent judgments, so a "Stop adding / Bullish"
        # holding must not show "Bullish" tinted by the verdict's colour.
        verdict_start = start + len(heading_prefix)
        verdict_end = verdict_start + len(verdict)
        colored_ranges.append((verdict_start, verdict_end, VERDICT_COLORS.get(verdict, STATUS_COLORS["warning"])))

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
        elif not a.get("pays_dividend", True):
            add_line("   Pays no dividend - dividend safety does not apply.")

        if written.get("case_for"):
            add_line(f"   Case for: {written['case_for']}")
        if written.get("case_against"):
            add_line(f"   Case against: {written['case_against']}")
        if written.get("what_would_change_my_mind"):
            add_line(f"   What would change my mind: {written['what_would_change_my_mind']}")
        if written.get("override_reason"):
            # Audit against what the score said WHEN the agent recorded the
            # override (computed_verdict), not today's recomputed verdict —
            # analyze_portfolio reruns on every Doc sync, which happens more
            # often than analysis passes, so the two drift apart. Falls back
            # to the recomputed verdict for older entries that predate the field.
            computed_verdict = written.get("computed_verdict", a["verdict"])
            add_line(f"   Overridden from the computed {computed_verdict}: {written['override_reason']}")
        if not written:
            add_line("   No written analysis yet - run the analysis pass to add one.")
        add_line("")

    return "\n".join(lines_text), title_range, bold_ranges, colored_ranges


def render_next_euro_text(
    analyses: list[dict], ranked: list[dict]
) -> tuple[str, tuple[int, int], list[tuple[int, int]]]:
    """The "Where Your Next Euro Goes" page: every rankable holding ordered by
    add score, so the monthly contribution decision is one glance. Per spec
    §4, holdings with insufficient data are excluded from the ranking but
    still reported underneath it, so a holding the owner owns never just
    disappears silently."""
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
        add_line("Not enough data to rank any holding yet.")
    else:
        for r in ranked:
            start, end = add_line(f"{r['rank']}. {r['company']} ({r['ticker']}) - {r['verdict']} ({round(r['add_score'])}/100)")
            bold_ranges.append((start, end))
            if r.get("strongest") and r.get("weakest"):
                add_line(f"   Strongest: {r['strongest'][0]} ({round(r['strongest'][1])}) | Weakest: {r['weakest'][0]} ({round(r['weakest'][1])})")
            add_line("")

    unrankable = [a for a in analyses if a.get("add_score") is None]
    if unrankable:
        add_line("Not ranked - insufficient data:")
        for a in unrankable:
            add_line(f"   {a['company']} ({a['ticker']})")

    return "\n".join(lines_text), title_range, bold_ranges


def get_or_create_doc(docs_service, drive_service, title: str = DOC_TITLE):
    results = drive_service.files().list(
        q=f"name='{title}' and mimeType='application/vnd.google-apps.document' and trashed=false"
    ).execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    doc = docs_service.documents().create(body={"title": title}).execute()
    return doc["documentId"]


def _hex_to_rgb_fraction(hex_color: str) -> dict:
    hex_color = hex_color.lstrip("#")
    return {
        "red": int(hex_color[0:2], 16) / 255,
        "green": int(hex_color[2:4], 16) / 255,
        "blue": int(hex_color[4:6], 16) / 255,
    }


def write_doc(
    docs_service,
    doc_id: str,
    sections: list[dict],
    picks: list[dict],
    allocation: dict,
    analyses: list[dict],
    ranked: list[dict],
    latest_analysis: dict,
) -> None:
    doc = docs_service.documents().get(documentId=doc_id).execute()
    end_index = doc["body"]["content"][-1]["endIndex"]

    requests = []
    if end_index > 2:
        requests.append({"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index - 1}}})

    # Front pages, in order, each followed by a page break:
    # (text, title_range, bold_ranges, colored_ranges, monospace_ranges).
    allocation_text, allocation_title, allocation_bold, allocation_mono = render_allocation_text(allocation)
    top_picks_text, top_picks_colored, top_picks_title, top_picks_bold = render_top_picks_text(picks)
    analyst_text, analyst_title, analyst_bold, analyst_colored = render_analyst_text(analyses, latest_analysis)
    next_euro_text, next_euro_title, next_euro_bold = render_next_euro_text(analyses, ranked)
    legend_text, legend_bold, legend_title = render_legend_text()
    front_pages = [
        (allocation_text, allocation_title, allocation_bold, [], allocation_mono),
        (top_picks_text, top_picks_title, top_picks_bold, top_picks_colored, []),
        (analyst_text, analyst_title, analyst_bold, analyst_colored, []),
        (next_euro_text, next_euro_title, next_euro_bold, [], []),
        (legend_text, legend_title, legend_bold, [], []),
    ]

    section_texts = []
    all_colored_ranges = []
    all_heading_ranges = []  # company headings: HEADING_2 + border
    all_monospace_ranges = []
    all_bold_ranges = []  # plain bold (legend terms, News/Fundamentals/Watch labels)
    all_heading1_ranges = []  # front-page titles: HEADING_1, no border

    cursor = 1  # Docs body content starts at index 1
    for text, title_range, bold_ranges, colored_ranges, monospace_ranges in front_pages:
        requests.append({"insertText": {"location": {"index": cursor}, "text": text}})
        all_heading1_ranges.append((title_range[0] + cursor, title_range[1] + cursor))
        all_bold_ranges += [(s + cursor, e + cursor) for s, e in bold_ranges if (s, e) != title_range]
        all_colored_ranges += [(s + cursor, e + cursor, hex_color) for s, e, hex_color in colored_ranges]
        all_monospace_ranges += [(s + cursor, e + cursor) for s, e in monospace_ranges]
        cursor += len(text)

        requests.append({"insertPageBreak": {"location": {"index": cursor}}})
        cursor += 1  # a page break consumes exactly one index

    company_start_cursor = cursor
    for section in sections:
        text, colored_ranges, heading_range, monospace_ranges, bold_ranges = render_section_text(section)
        section_texts.append(text)
        all_colored_ranges += [(s + cursor, e + cursor, hex_color) for s, e, hex_color in colored_ranges]
        all_heading_ranges.append((heading_range[0] + cursor, heading_range[1] + cursor))
        all_monospace_ranges += [(s + cursor, e + cursor) for s, e in monospace_ranges]
        all_bold_ranges += [(s + cursor, e + cursor) for s, e in bold_ranges]
        cursor += len(text) + 2  # +2: the "\n\n" separator inserted between sections below

    companies_full_text = "\n\n".join(section_texts) + "\n"
    requests.append({"insertText": {"location": {"index": company_start_cursor}, "text": companies_full_text}})

    for start, end in all_heading1_ranges:
        requests.append(
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "paragraphStyle": {"namedStyleType": "HEADING_1"},
                    "fields": "namedStyleType",
                }
            }
        )

    for start, end in all_heading_ranges:
        requests.append(
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "paragraphStyle": {
                        "namedStyleType": "HEADING_2",
                        "borderBottom": {
                            "color": {"color": {"rgbColor": {"red": 0.76, "green": 0.75, "blue": 0.72}}},
                            "width": {"magnitude": 1, "unit": "PT"},
                            "padding": {"magnitude": 4, "unit": "PT"},
                            "dashStyle": "SOLID",
                        },
                    },
                    "fields": "namedStyleType,borderBottom",
                }
            }
        )

    for start, end in all_monospace_ranges:
        requests.append(
            {
                "updateTextStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "textStyle": {"weightedFontFamily": {"fontFamily": MONOSPACE_FONT}},
                    "fields": "weightedFontFamily",
                }
            }
        )

    for start, end in all_bold_ranges:
        requests.append(
            {
                "updateTextStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "textStyle": {"bold": True},
                    "fields": "bold",
                }
            }
        )

    for start, end, hex_color in all_colored_ranges:
        requests.append(
            {
                "updateTextStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "textStyle": {"foregroundColor": {"color": {"rgbColor": _hex_to_rgb_fraction(hex_color)}}, "bold": True},
                    "fields": "foregroundColor,bold",
                }
            }
        )

    docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()


def main():
    holdings = load_portfolio()
    latest_analysis = {
        h["ticker"]: (latest_by_date(load_yaml_list(analysis_yaml_path(h["ticker"]), "entries")) or {})
        for h in holdings
    }
    previous_analysis = {
        h["ticker"]: (previous_analysis_entry(load_yaml_list(analysis_yaml_path(h["ticker"]), "entries")) or {})
        for h in holdings
    }
    latest_history = latest_history_by_ticker()
    previous_history = previous_history_by_ticker()

    sections = build_summary_sections(holdings, latest_analysis, latest_history, previous_analysis, previous_history)
    picks = compute_top_picks(holdings, latest_history, latest_analysis, top_n=TOP_PICKS_COUNT)
    allocation = compute_allocation(
        holdings, latest_history, {h["ticker"]: (latest_fundamentals_snapshot(h["ticker"]) or {}) for h in holdings}
    )
    analyses = analyze_portfolio(
        holdings, {h["ticker"]: (latest_fundamentals_snapshot(h["ticker"]) or {}) for h in holdings},
        latest_history, allocation,
    )
    ranked = rank_next_euro(analyses)

    creds = get_credentials()
    docs_service = build("docs", "v1", credentials=creds)
    drive_service = build("drive", "v3", credentials=creds)

    doc_id = get_or_create_doc(docs_service, drive_service)
    write_doc(docs_service, doc_id, sections, picks, allocation, analyses, ranked, latest_analysis)
    print(f"Synced summary for {len(holdings)} holdings to Google Doc: https://docs.google.com/document/d/{doc_id}")


if __name__ == "__main__":
    main()
