from tools.ticker_tab import (
    CHART_ANCHOR_COL,
    HELPER_COLUMNS,
    TAB_MIN_COLS,
    TICKER_TAB_HEADER,
    build_chart_requests,
    build_ticker_tab_rows,
    existing_chart_ids,
    hex_to_rgb_fraction,
    resize_target,
)
from tools.technicals import INDICATOR_KEYS


def _indicator(date, **values):
    row = {"date": date, **{k: None for k in INDICATOR_KEYS}}
    row.update(values)
    return row


def test_header_has_visible_columns_then_hidden_helpers_last():
    assert TICKER_TAB_HEADER[:11] == [
        "Date", "Close", "RSI", "MACD", "Signal", "Histogram",
        "Konkorde Green", "Konkorde Brown", "Konkorde Blue", "Konkorde Avg", "News",
    ]
    assert TICKER_TAB_HEADER[-len(HELPER_COLUMNS):] == HELPER_COLUMNS
    assert CHART_ANCHOR_COL == len(TICKER_TAB_HEADER)
    assert TAB_MIN_COLS == CHART_ANCHOR_COL + 1


def test_build_ticker_tab_rows_numbers_news_and_blanks():
    price_rows = [
        {"date": "2026-09-16", "close": "163.9"},
        {"date": "2026-09-15", "close": "160.0"},
    ]
    news = [{"date": "2026-09-16", "title": "Honeywell raises guidance", "url": "https://x", "source": "Reuters", "fetched_at": "now"}]
    indicators = [
        _indicator("2026-09-15"),
        _indicator("2026-09-16", rsi=61.23456, macd=1.234567, macd_signal=1.0, macd_hist=0.234567,
                   konkorde_green=12.346, konkorde_brown=40.0, konkorde_blue=-5.5, konkorde_avg=38.0),
    ]

    rows = build_ticker_tab_rows(price_rows, news, indicators)

    assert rows[0] == TICKER_TAB_HEADER
    # warm-up row: numbers blank, helper bands still present, sorted by date
    assert rows[1] == ["2026-09-15", 160.0, "", "", "", "", "", "", "", "", "", 70, 30, "", ""]
    assert rows[2] == [
        "2026-09-16", 163.9, 61.23, 1.2346, 1.0, 0.2346,
        12.35, 40.0, -5.5, 38.0, "Honeywell raises guidance",
        70, 30, 0.2346, "",
    ]


def test_build_ticker_tab_rows_bad_close_becomes_blank_not_raise_or_nan():
    # A non-numeric close, an empty close, and the literal string "nan" (the
    # shape fetch_prices.py's f"{float(x):.4f}" formatting emits for a NaN
    # close) must all become a blank cell, not raise ValueError mid-loop and
    # not write a bare "nan" token, which the Sheets API rejects.
    price_rows = [
        {"date": "2026-09-14", "close": "not-a-number"},
        {"date": "2026-09-15", "close": ""},
        {"date": "2026-09-16", "close": "nan"},
    ]
    rows = build_ticker_tab_rows(price_rows, [], [])

    assert rows[1][TICKER_TAB_HEADER.index("Close")] == ""
    assert rows[2][TICKER_TAB_HEADER.index("Close")] == ""
    assert rows[3][TICKER_TAB_HEADER.index("Close")] == ""


def test_negative_histogram_goes_to_hist_minus_column():
    rows = build_ticker_tab_rows(
        [{"date": "2026-09-16", "close": "10"}], [], [_indicator("2026-09-16", macd_hist=-0.5)]
    )
    assert rows[1][TICKER_TAB_HEADER.index("Hist +")] == ""
    assert rows[1][TICKER_TAB_HEADER.index("Hist -")] == -0.5


def test_existing_chart_ids_only_for_that_sheet():
    metadata = {"sheets": [
        {"properties": {"sheetId": 1}, "charts": [{"chartId": 11}, {"chartId": 12}]},
        {"properties": {"sheetId": 2}},
    ]}
    assert existing_chart_ids(metadata, 1) == [11, 12]
    assert existing_chart_ids(metadata, 2) == []
    assert existing_chart_ids(metadata, 99) == []


def _add_chart_specs(requests):
    return [r["addChart"]["chart"]["spec"] for r in requests if "addChart" in r]


def test_build_chart_requests_replaces_charts_hides_helpers_and_freezes():
    requests = build_chart_requests(sheet_id=7, row_count=251, existing_ids=[11, 12])

    deletes = [r["deleteEmbeddedObject"]["objectId"] for r in requests if "deleteEmbeddedObject" in r]
    assert deletes == [11, 12]
    # deletes come before the new charts are added
    first_add = next(i for i, r in enumerate(requests) if "addChart" in r)
    assert all("deleteEmbeddedObject" not in r for r in requests[first_add:])

    hide = next(r["updateDimensionProperties"] for r in requests if "updateDimensionProperties" in r)
    assert hide["range"] == {
        "sheetId": 7, "dimension": "COLUMNS",
        "startIndex": TICKER_TAB_HEADER.index(HELPER_COLUMNS[0]),
        "endIndex": len(TICKER_TAB_HEADER),
    }
    assert hide["properties"] == {"hiddenByUser": True}

    freeze = next(r["updateSheetProperties"] for r in requests if "updateSheetProperties" in r)
    assert freeze["properties"]["gridProperties"]["frozenRowCount"] == 1

    titles = [s["title"] for s in _add_chart_specs(requests)]
    assert titles == ["Price (Close)", "MACD (12, 26, 9)", "RSI (14)", "Konkorde"]


def test_charts_plot_hidden_helpers_and_stack_to_the_right():
    requests = build_chart_requests(sheet_id=7, row_count=251, existing_ids=[])
    adds = [r["addChart"]["chart"] for r in requests if "addChart" in r]

    rows = []
    for chart in adds:
        assert chart["spec"]["hiddenDimensionStrategy"] == "SHOW_ALL"
        anchor = chart["position"]["overlayPosition"]["anchorCell"]
        assert anchor["sheetId"] == 7 and anchor["columnIndex"] == CHART_ANCHOR_COL
        rows.append(anchor["rowIndex"])
    assert rows == sorted(rows) and len(set(rows)) == 4


def test_chart_series_use_full_contiguous_range():
    """Charts must use a single contiguous sourceRange covering all rows (header + data)."""
    requests = build_chart_requests(sheet_id=7, row_count=251, existing_ids=[])
    spec = _add_chart_specs(requests)[0]["basicChart"]
    sources = spec["domains"][0]["domain"]["sourceRange"]["sources"]

    assert spec["headerCount"] == 1
    assert len(sources) == 1
    assert sources[0]["startRowIndex"] == 0 and sources[0]["endRowIndex"] == 251


def test_short_tab_uses_one_contiguous_range():
    requests = build_chart_requests(sheet_id=7, row_count=30, existing_ids=[])
    sources = _add_chart_specs(requests)[0]["basicChart"]["domains"][0]["domain"]["sourceRange"]["sources"]
    assert len(sources) == 1
    assert sources[0]["startRowIndex"] == 0 and sources[0]["endRowIndex"] == 30


def _series_columns(spec):
    return [
        TICKER_TAB_HEADER[s["series"]["sourceRange"]["sources"][-1]["startColumnIndex"]]
        for s in spec["basicChart"]["series"]
    ]


def test_each_chart_plots_the_right_columns():
    specs = _add_chart_specs(build_chart_requests(sheet_id=7, row_count=251, existing_ids=[]))

    assert _series_columns(specs[0]) == ["Close"]
    assert _series_columns(specs[1]) == ["Hist +", "Hist -", "MACD", "Signal"]
    assert _series_columns(specs[2]) == ["RSI", "RSI 70", "RSI 30"]
    assert _series_columns(specs[3]) == ["Konkorde Green", "Konkorde Brown", "Konkorde Blue", "Konkorde Avg"]
    assert [s["type"] for s in specs[1]["basicChart"]["series"]] == ["COLUMN", "COLUMN", "LINE", "LINE"]
    assert [s["type"] for s in specs[3]["basicChart"]["series"]] == ["AREA", "AREA", "AREA", "LINE"]


def test_rsi_chart_axis_fixed_0_to_100():
    spec = _add_chart_specs(build_chart_requests(sheet_id=7, row_count=251, existing_ids=[]))[2]
    left = next(a for a in spec["basicChart"]["axis"] if a["position"] == "LEFT_AXIS")
    assert left["viewWindowOptions"] == {"viewWindowMin": 0, "viewWindowMax": 100, "viewWindowMode": "EXPLICIT"}


def test_hex_to_rgb_fraction():
    assert hex_to_rgb_fraction("#ff0000") == {"red": 1.0, "green": 0.0, "blue": 0.0}


def test_combo_charts_are_explicitly_unstacked():
    """MACD and Konkorde COMBO charts must have stackedType: NOT_STACKED explicitly set."""
    specs = _add_chart_specs(build_chart_requests(sheet_id=7, row_count=251, existing_ids=[]))

    # Specs are: Price (LINE), MACD (COMBO), RSI (LINE), Konkorde (COMBO)
    macd_spec = specs[1]["basicChart"]
    konkorde_spec = specs[3]["basicChart"]

    assert macd_spec.get("stackedType") == "NOT_STACKED"
    assert konkorde_spec.get("stackedType") == "NOT_STACKED"


def test_series_colors_and_band_linestyle():
    """Assert that every series has the correct color and dashed bands have correct lineStyle."""
    from tools.ticker_tab import CHART_COLORS

    specs = _add_chart_specs(build_chart_requests(sheet_id=7, row_count=251, existing_ids=[]))

    # Price chart: one series
    price_series = specs[0]["basicChart"]["series"]
    assert len(price_series) == 1
    assert price_series[0]["colorStyle"]["rgbColor"] == hex_to_rgb_fraction(CHART_COLORS["primary"])

    # MACD chart: Hist+, Hist-, MACD, Signal
    macd_series = specs[1]["basicChart"]["series"]
    assert len(macd_series) == 4
    colors = ["up", "down", "primary", "secondary"]
    for i, color_key in enumerate(colors):
        assert macd_series[i]["colorStyle"]["rgbColor"] == hex_to_rgb_fraction(CHART_COLORS[color_key])

    # RSI chart: RSI, RSI 70 (dashed band), RSI 30 (dashed band)
    rsi_series = specs[2]["basicChart"]["series"]
    assert len(rsi_series) == 3
    assert rsi_series[0]["colorStyle"]["rgbColor"] == hex_to_rgb_fraction(CHART_COLORS["primary"])
    assert rsi_series[1]["colorStyle"]["rgbColor"] == hex_to_rgb_fraction(CHART_COLORS["band"])
    assert rsi_series[1]["lineStyle"] == {"type": "MEDIUM_DASHED", "width": 1}
    assert rsi_series[2]["colorStyle"]["rgbColor"] == hex_to_rgb_fraction(CHART_COLORS["band"])
    assert rsi_series[2]["lineStyle"] == {"type": "MEDIUM_DASHED", "width": 1}

    # Konkorde chart: Green, Brown, Blue, Avg
    konkorde_series = specs[3]["basicChart"]["series"]
    assert len(konkorde_series) == 4
    konkorde_colors = ["konkorde_green", "konkorde_brown", "konkorde_blue", "konkorde_avg"]
    for i, color_key in enumerate(konkorde_colors):
        assert konkorde_series[i]["colorStyle"]["rgbColor"] == hex_to_rgb_fraction(CHART_COLORS[color_key])


def test_all_chart_ranges_are_single_contiguous():
    """Google Sheets API requires all sourceRanges to be contiguous.
    This test verifies every domain and series uses exactly one sourceRange."""
    specs = _add_chart_specs(build_chart_requests(sheet_id=7, row_count=251, existing_ids=[]))

    for i, spec in enumerate(specs):
        basic_chart = spec["basicChart"]
        # Check domain has exactly one sourceRange
        domain_sources = basic_chart["domains"][0]["domain"]["sourceRange"]["sources"]
        assert len(domain_sources) == 1, f"Chart {i} domain has {len(domain_sources)} sources, expected 1"

        # Check all series have exactly one sourceRange
        for j, series in enumerate(basic_chart["series"]):
            series_sources = series["series"]["sourceRange"]["sources"]
            assert len(series_sources) == 1, f"Chart {i} series {j} has {len(series_sources)} sources, expected 1"


def test_resize_target_none_when_grid_already_fits():
    # Plenty of rows and at least TAB_MIN_COLS columns already -> no resize call needed.
    assert resize_target(current_rows=500, current_cols=TAB_MIN_COLS, needed_rows=251) is None
    assert resize_target(current_rows=500, current_cols=TAB_MIN_COLS + 5, needed_rows=251) is None


def test_resize_target_grows_rows_when_price_history_grows_past_grid():
    # A grown price history must always still fit: needed_rows exceeds the
    # existing grid's row count, so it must resize up to at least fit it.
    assert resize_target(current_rows=100, current_cols=TAB_MIN_COLS, needed_rows=251) == (251, TAB_MIN_COLS)


def test_resize_target_grows_cols_when_grid_narrower_than_min():
    assert resize_target(current_rows=500, current_cols=TAB_MIN_COLS - 1, needed_rows=251) == (500, TAB_MIN_COLS)


def test_resize_target_never_shrinks_below_current_grid():
    # needed_rows (10) is well below the current grid (1000) and cols already
    # meet TAB_MIN_COLS -> no resize call at all, so the grid stays put
    # rather than shrinking down to fit the smaller row count.
    assert resize_target(current_rows=1000, current_cols=TAB_MIN_COLS, needed_rows=10) is None
