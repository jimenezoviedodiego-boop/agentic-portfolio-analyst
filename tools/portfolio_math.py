def compute_value_and_gp(shares: float, price_local: float, avg_cost_local: float, fx_rate: float) -> dict:
    value_eur = shares * price_local * fx_rate
    cost_eur = shares * avg_cost_local * fx_rate
    if cost_eur > 0:
        gp_eur = value_eur - cost_eur
        gp_pct = gp_eur / cost_eur * 100
    else:
        # Unknown/zero cost basis: don't fabricate a "gain" equal to the full
        # position value — that would silently inflate the portfolio-wide G/P
        # total (see the KD incident, broker-reported cost basis of 0.00).
        gp_eur = None
        gp_pct = None
    return {"value_eur": value_eur, "gp_eur": gp_eur, "gp_pct": gp_pct}
