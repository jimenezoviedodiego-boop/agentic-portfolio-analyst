from tools.fetch_fx_rate import cache_path, get_rate


def test_eur_returns_one_without_calling_fetch_fn():
    calls = []
    rate = get_rate("EUR", fetch_fn=lambda c: calls.append(c) or 999.0)
    assert rate == 1.0
    assert calls == []


def test_fetches_and_caches_rate(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path))
    calls = []

    def fake_fetch(currency):
        calls.append(currency)
        return 0.87

    rate1 = get_rate("USD", today_str="2026-09-16", fetch_fn=fake_fetch)
    assert rate1 == 0.87
    assert calls == ["USD"]

    # second call same day: served from cache, fetch_fn not called again
    rate2 = get_rate("USD", today_str="2026-09-16", fetch_fn=fake_fetch)
    assert rate2 == 0.87
    assert calls == ["USD"]

    assert cache_path("USD").exists()


def test_refetches_on_new_day(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path))
    calls = []

    def fake_fetch(currency):
        calls.append(currency)
        return 0.87 + len(calls) * 0.01

    get_rate("USD", today_str="2026-09-16", fetch_fn=fake_fetch)
    rate2 = get_rate("USD", today_str="2026-09-17", fetch_fn=fake_fetch)
    assert calls == ["USD", "USD"]
    assert rate2 == 0.89
