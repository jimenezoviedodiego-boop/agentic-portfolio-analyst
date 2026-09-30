import pytest


@pytest.fixture(autouse=True)
def _default_portfolio_data_dir(tmp_path, monkeypatch):
    """Safety net: point PORTFOLIO_DATA_DIR at a throwaway directory for every
    test by default, so a test that forgets to set it explicitly can never
    accidentally read or write the owner's real data/ directory (which holds real
    financial data). Tests that call monkeypatch.setenv("PORTFOLIO_DATA_DIR", ...)
    themselves simply overwrite this default — monkeypatch's per-test teardown
    means later setenv calls in a test always win over this fixture.
    """
    monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path))
