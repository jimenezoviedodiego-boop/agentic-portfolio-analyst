"""One Sheet tab per ticker: daily close + technical indicator columns,
and the native Sheets charts (Price, MACD, RSI, Konkorde) drawn from
them. Pure functions returning rows / batch_update requests — the Google
calls themselves live in sync_google_sheet."""

import math

TICKER_TAB_HEADER = [
    "Date", "Close", "RSI", "MACD", "Signal", "Histogram",
    "Konkorde Green", "Konkorde Brown", "Konkorde Blue", "Konkorde Avg", "News",
    # Hidden helpers the charts need: flat 70/30 RSI bands, and the MACD
    # histogram split by sign so it can render as green/red columns.
    "RSI 70", "RSI 30", "Hist +", "Hist -",
]
HELPER_COLUMNS = ["RSI 70", "RSI 30", "Hist +", "Hist -"]

CHART_ANCHOR_COL = len(TICKER_TAB_HEADER)  # charts sit just right of the helpers
TAB_MIN_COLS = CHART_ANCHOR_COL + 1  # an overlay's anchor cell must exist in the grid
CHART_ROW_SPACING = 17
CHART_WIDTH_PX = 900
CHART_HEIGHT_PX = 320

# Validated colorblind-safe with the dataviz palette validator.
CHART_COLORS = {
    "up": "#2ea36b",
    "down": "#d64545",
    "primary": "#2f6fd6",
    "secondary": "#c96a12",
    "konkorde_green": "#2ea36b",
    "konkorde_brown": "#a0522d",
    "konkorde_blue": "#2f6fd6",
    "konkorde_avg": "#d64545",
    "band": "#9e9e9e",
}


def hex_to_rgb_fraction(hex_color: str) -> dict:
    hex_color = hex_color.lstrip("#")
    return {
        "red": int(hex_color[0:2], 16) / 255,
        "green": int(hex_color[2:4], 16) / 255,
        "blue": int(hex_color[4:6], 16) / 255,
    }


def _num(value: float | None, digits: int = 4):
    return "" if value is None else round(value, digits)


def _close(value, digits: int = 4):
    """None-safe close: a missing/unparseable/NaN close becomes an empty
    cell instead of raising ValueError mid-loop or writing the literal
    string "nan" (which the Sheets API rejects) — same treatment as the
    indicator fields via _num()."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return ""
    return _num(parsed if math.isfinite(parsed) else None, digits)


def build_ticker_tab_rows(price_rows: list[dict], news_entries: list[dict], indicator_rows: list[dict]) -> list[list]:
    news_by_date: dict[str, list[str]] = {}
    for n in news_entries:
        news_by_date.setdefault(n["date"], []).append(n["title"])
    indicators_by_date = {r["date"]: r for r in indicator_rows}

    rows = [TICKER_TAB_HEADER]
    for p in sorted(price_rows, key=lambda r: r["date"]):
        ind = indicators_by_date.get(p["date"], {})
        hist = ind.get("macd_hist")
        rows.append([
            p["date"], _close(p["close"]),
            _num(ind.get("rsi"), 2),
            _num(ind.get("macd")), _num(ind.get("macd_signal")), _num(hist),
            _num(ind.get("konkorde_green"), 2), _num(ind.get("konkorde_brown"), 2),
            _num(ind.get("konkorde_blue"), 2), _num(ind.get("konkorde_avg"), 2),
            "; ".join(news_by_date.get(p["date"], [])),
            70, 30,
            _num(hist) if hist is not None and hist >= 0 else "",
            _num(hist) if hist is not None and hist < 0 else "",
        ])
    return rows


def resize_target(current_rows: int, current_cols: int, needed_rows: int) -> tuple[int, int] | None:
    """The (rows, cols) an existing ticker tab's grid should be resized to
    before writing `needed_rows` rows, or None if the current grid already
    fits (no resize call needed). A grown price history always still fits:
    resizing never shrinks below the current row/col count."""
    if needed_rows <= current_rows and current_cols >= TAB_MIN_COLS:
        return None
    return max(needed_rows, current_rows), max(TAB_MIN_COLS, current_cols)


def existing_chart_ids(metadata: dict, sheet_id: int) -> list[int]:
    for sheet in metadata.get("sheets", []):
        if sheet["properties"]["sheetId"] == sheet_id:
            return [c["chartId"] for c in sheet.get("charts", [])]
    return []


def _col(name: str) -> int:
    return TICKER_TAB_HEADER.index(name)


def _grid_range(sheet_id: int, col: int, start_row: int, end_row: int) -> dict:
    return {
        "sheetId": sheet_id,
        "startRowIndex": start_row, "endRowIndex": end_row,
        "startColumnIndex": col, "endColumnIndex": col + 1,
    }


def _chart_data(sheet_id: int, col: int, row_count: int) -> dict:
    """Header row plus all data rows in a single contiguous range.
    The header row is kept inside the range so the chart names each
    series from row 0, with headerCount: 1."""
    return {"sourceRange": {"sources": [_grid_range(sheet_id, col, 0, row_count)]}}


def _series(sheet_id: int, column: str, row_count: int, series_type: str, color: str, dashed: bool = False) -> dict:
    series = {
        "series": _chart_data(sheet_id, _col(column), row_count),
        "targetAxis": "LEFT_AXIS",
        "type": series_type,
        "colorStyle": {"rgbColor": hex_to_rgb_fraction(CHART_COLORS[color])},
    }
    if series_type == "LINE":
        series["lineStyle"] = {"type": "MEDIUM_DASHED", "width": 1} if dashed else {"type": "SOLID", "width": 2}
    return series


def _add_chart(sheet_id: int, row_count: int, slot: int, title: str, chart_type: str,
               series: list[dict], legend: str = "BOTTOM_LEGEND", left_axis: dict | None = None,
               stacked_type: str | None = None) -> dict:
    left = {"position": "LEFT_AXIS", **(left_axis or {})}
    basic_chart = {
        "chartType": chart_type,
        "legendPosition": legend,
        "headerCount": 1,
        "axis": [{"position": "BOTTOM_AXIS"}, left],
        "domains": [{"domain": _chart_data(sheet_id, _col("Date"), row_count)}],
        "series": series,
    }
    if stacked_type is not None:
        basic_chart["stackedType"] = stacked_type
    return {
        "addChart": {
            "chart": {
                "spec": {
                    "title": title,
                    # Helper columns are hidden; without SHOW_ALL Sheets
                    # silently drops hidden columns from charts.
                    "hiddenDimensionStrategy": "SHOW_ALL",
                    "basicChart": basic_chart,
                },
                "position": {
                    "overlayPosition": {
                        "anchorCell": {
                            "sheetId": sheet_id,
                            "rowIndex": slot * CHART_ROW_SPACING,
                            "columnIndex": CHART_ANCHOR_COL,
                        },
                        "widthPixels": CHART_WIDTH_PX,
                        "heightPixels": CHART_HEIGHT_PX,
                    }
                },
            }
        }
    }


def build_chart_requests(sheet_id: int, row_count: int, existing_ids: list[int]) -> list[dict]:
    """Everything a ticker tab needs after its values are written, as one
    batch_update: drop the previous sync's charts (so they don't pile up),
    freeze the header, hide the helper columns, add the 4 charts."""
    requests: list[dict] = [{"deleteEmbeddedObject": {"objectId": chart_id}} for chart_id in existing_ids]

    requests.append({
        "updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount",
        }
    })
    first_helper = _col(HELPER_COLUMNS[0])
    requests.append({
        "updateDimensionProperties": {
            "range": {
                "sheetId": sheet_id, "dimension": "COLUMNS",
                "startIndex": first_helper, "endIndex": first_helper + len(HELPER_COLUMNS),
            },
            "properties": {"hiddenByUser": True},
            "fields": "hiddenByUser",
        }
    })

    def s(column, series_type, color, dashed=False):
        return _series(sheet_id, column, row_count, series_type, color, dashed)

    requests += [
        _add_chart(sheet_id, row_count, 0, "Price (Close)", "LINE",
                   [s("Close", "LINE", "primary")], legend="NO_LEGEND"),
        _add_chart(sheet_id, row_count, 1, "MACD (12, 26, 9)", "COMBO", [
            s("Hist +", "COLUMN", "up"),
            s("Hist -", "COLUMN", "down"),
            s("MACD", "LINE", "primary"),
            s("Signal", "LINE", "secondary"),
        ], stacked_type="NOT_STACKED"),
        _add_chart(sheet_id, row_count, 2, "RSI (14)", "LINE", [
            s("RSI", "LINE", "primary"),
            s("RSI 70", "LINE", "band", dashed=True),
            s("RSI 30", "LINE", "band", dashed=True),
        ], left_axis={"viewWindowOptions": {"viewWindowMin": 0, "viewWindowMax": 100, "viewWindowMode": "EXPLICIT"}}),
        _add_chart(sheet_id, row_count, 3, "Konkorde", "COMBO", [
            s("Konkorde Green", "AREA", "konkorde_green"),
            s("Konkorde Brown", "AREA", "konkorde_brown"),
            s("Konkorde Blue", "AREA", "konkorde_blue"),
            s("Konkorde Avg", "LINE", "konkorde_avg"),
        ], stacked_type="NOT_STACKED"),
    ]
    return requests
