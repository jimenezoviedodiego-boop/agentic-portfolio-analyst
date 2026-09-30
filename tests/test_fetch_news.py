import time

from tools.fetch_news import google_news_rss_url, parse_feed_entries, save_news, news_jsonl_path
from tools.portfolio_lib import load_jsonl_rows


class FakeFeed:
    def __init__(self, entries, bozo=0):
        self.entries = entries
        self.bozo = bozo


def test_google_news_rss_url_encodes_company_name():
    url = google_news_rss_url("Honeywell International")
    assert url.startswith("https://news.google.com/rss/search?q=Honeywell")
    assert "hl=en-US" in url


def test_parse_feed_entries_extracts_fields():
    feed = FakeFeed(
        [
            {
                "title": "Honeywell raises guidance",
                "link": "https://example.com/a",
                "published": "Mon, 15 Sep 2026 10:00:00 GMT",
                "published_parsed": time.struct_time((2026, 9, 15, 10, 0, 0, 0, 0, 0)),
                "source": {"title": "Reuters"},
            }
        ]
    )
    entries = parse_feed_entries(feed)
    assert entries[0]["title"] == "Honeywell raises guidance"
    assert entries[0]["url"] == "https://example.com/a"
    assert entries[0]["date"] == "2026-09-15"
    assert entries[0]["source"] == "Reuters"
    assert "fetched_at" in entries[0]


def test_save_news_dedups_by_url(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path))
    entry = {"date": "2026-09-15", "title": "A", "source": "X", "url": "https://a", "fetched_at": "now"}
    added1 = save_news("HON", [entry])
    added2 = save_news("HON", [entry])
    assert added1 == 1
    assert added2 == 0
    assert len(load_jsonl_rows(news_jsonl_path("HON"))) == 1
