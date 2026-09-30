import pytest

from tools.portfolio_math import compute_value_and_gp


def test_same_currency_holding_uses_fx_rate_of_one():
    # EUR-denominated example: 20 shares, price 60.98, avg cost 50.00
    result = compute_value_and_gp(shares=20, price_local=60.98, avg_cost_local=50.0, fx_rate=1.0)
    assert result["value_eur"] == pytest.approx(1219.60, abs=0.01)
    assert result["gp_eur"] > 0
    assert result["gp_pct"] == pytest.approx(21.96, abs=0.1)


def test_cross_currency_holding_applies_fx_rate():
    result = compute_value_and_gp(shares=10, price_local=100.0, avg_cost_local=80.0, fx_rate=0.9)
    assert result["value_eur"] == pytest.approx(900.0)
    assert result["gp_eur"] == pytest.approx(900.0 - 720.0)
    assert result["gp_pct"] == pytest.approx(25.0)


def test_zero_avg_cost_returns_none_gp_pct():
    # KD: broker-reported breakeven price of 0.00 (spinoff share, no tracked cost basis)
    result = compute_value_and_gp(shares=3, price_local=90.925, avg_cost_local=0.0, fx_rate=0.9)
    assert result["gp_pct"] is None
    assert result["value_eur"] == pytest.approx(3 * 90.925 * 0.9)
    assert result["gp_eur"] is None  # unknown cost basis must not leak a phantom gain
