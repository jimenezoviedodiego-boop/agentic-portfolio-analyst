"""Portfolio allocation: how the current value splits across positions,
sectors and countries, plus concentration flags against simple rules of
thumb. Pure computation over already-fetched data (latest history row for
value/G-P, latest fundamentals snapshot for sector/country) - shared by the
Doc's allocation page and the Sheet's Allocation tab."""

from tools.scoring import to_float

# Common diversification rules of thumb, not hard limits: no single stock
# above ~10% of the portfolio, no single sector above ~25%.
POSITION_LIMIT_PCT = 10.0
SECTOR_LIMIT_PCT = 25.0

ETF_SECTOR_LABEL = "Broad-market ETF"
ETF_COUNTRY_LABEL = "Various (ETF)"
UNKNOWN_LABEL = "Unknown"


def _is_etf(fund: dict) -> bool:
    return fund.get("quote_type") == "ETF"


def holding_sector(fund: dict) -> str:
    if _is_etf(fund):
        return ETF_SECTOR_LABEL
    return fund.get("sector") or UNKNOWN_LABEL


def holding_country(fund: dict) -> str:
    if _is_etf(fund):
        return ETF_COUNTRY_LABEL
    return fund.get("country") or UNKNOWN_LABEL


def _group(positions: list[dict], key: str, total: float) -> list[dict]:
    groups: dict[str, dict] = {}
    for p in positions:  # positions arrive sorted by value, so tickers stay sorted too
        g = groups.setdefault(p[key], {"name": p[key], "value_eur": 0.0, "tickers": []})
        g["value_eur"] += p["value_eur"]
        g["tickers"].append(p["ticker"])
    for g in groups.values():
        g["weight_pct"] = g["value_eur"] / total * 100 if total else 0.0
    return sorted(groups.values(), key=lambda g: (-g["value_eur"], g["name"]))


def _position_flag(p: dict) -> str:
    flag = (
        f"{p['company']} ({p['ticker']}) is {p['weight_pct']:.1f}% of the portfolio - "
        f"above the {POSITION_LIMIT_PCT:.0f}% single-position rule of thumb."
    )
    invested = p["invested_eur"]
    if invested is not None and invested > 0 and p["value_eur"] >= 1.5 * invested:
        flag += (
            f" Most of that weight is growth: you put in about EUR {invested:,.0f}, "
            f"and it is now worth EUR {p['value_eur']:,.0f}."
        )
    return flag


def _sector_flag(s: dict) -> str:
    return (
        f"{s['name']} is {s['weight_pct']:.1f}% of the portfolio "
        f"({len(s['tickers'])} holdings: {', '.join(s['tickers'])}) - "
        f"above the {SECTOR_LIMIT_PCT:.0f}% single-sector rule of thumb."
    )


def compute_allocation(
    holdings: list[dict],
    latest_history: dict[str, dict],
    latest_fundamentals: dict[str, dict],
) -> dict:
    """Returns {total_eur, total_invested_eur, positions, sectors, countries,
    flags}. Positions are sorted by value (desc, ties by ticker); each
    carries weight_pct and invested_eur (value minus G/P - None when the
    cost basis is unknown, e.g. spin-off shares). Holdings with no recorded
    value are skipped. total_invested_eur sums only known cost bases."""
    positions = []
    for h in holdings:
        hist = latest_history.get(h["ticker"], {})
        value = to_float(hist.get("value_eur"))
        if value is None:
            continue
        gp = to_float(hist.get("gp_eur"))
        fund = latest_fundamentals.get(h["ticker"], {})
        positions.append(
            {
                "ticker": h["ticker"],
                "company": h["company"],
                "sector": holding_sector(fund),
                "industry": fund.get("industry") or "",
                "country": holding_country(fund),
                "is_etf": _is_etf(fund),
                "value_eur": value,
                "invested_eur": value - gp if gp is not None else None,
            }
        )

    total = sum(p["value_eur"] for p in positions)
    for p in positions:
        p["weight_pct"] = p["value_eur"] / total * 100 if total else 0.0
    positions.sort(key=lambda p: (-p["value_eur"], p["ticker"]))

    sectors = _group(positions, "sector", total)
    countries = _group(positions, "country", total)

    flags = [_position_flag(p) for p in positions if not p["is_etf"] and p["weight_pct"] > POSITION_LIMIT_PCT]
    flags += [
        _sector_flag(s) for s in sectors
        if s["name"] not in (ETF_SECTOR_LABEL, UNKNOWN_LABEL) and s["weight_pct"] > SECTOR_LIMIT_PCT
    ]

    return {
        "total_eur": total,
        "total_invested_eur": sum(p["invested_eur"] for p in positions if p["invested_eur"] is not None),
        "positions": positions,
        "sectors": sectors,
        "countries": countries,
        "flags": flags,
    }
