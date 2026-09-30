import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import feedparser

from tools.portfolio_lib import append_dedup_jsonl, data_dir


def news_jsonl_path(ticker: str) -> Path:
    return data_dir() / "news" / f"{ticker}.jsonl"


def google_news_rss_url(company: str) -> str:
    query = quote_plus(company)
    return f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


def parse_feed_entries(feed) -> list[dict]:
    fetched_at = datetime.now(timezone.utc).isoformat()
    entries = []
    for entry in feed.entries:
        published = entry.get("published", "")
        parsed = entry.get("published_parsed")
        if parsed:
            date_str = datetime(*parsed[:6]).date().isoformat()
        else:
            date_str = published[:10] if published else ""

        source = entry.get("source", "")
        source_title = source.get("title", "") if isinstance(source, dict) else str(source)

        entries.append(
            {
                "date": date_str,
                "title": entry.get("title", ""),
                "source": source_title,
                "url": entry.get("link", ""),
                "fetched_at": fetched_at,
            }
        )
    return entries


def fetch_news_live(ticker: str, company: str) -> list[dict]:
    feed = feedparser.parse(google_news_rss_url(company))

    # Check for feed parse/fetch errors
    if getattr(feed, "bozo", 0):
        bozo_exception = getattr(feed, "bozo_exception", "unknown error")
        print(f"{ticker}: feed parse error ({bozo_exception}) — no headlines fetched, this is likely a fetch issue, not 'no news today'")
        sys.exit(1)

    return parse_feed_entries(feed)


def save_news(ticker: str, entries: list[dict]) -> int:
    return append_dedup_jsonl(news_jsonl_path(ticker), entries, "url")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--company", required=True)
    args = parser.parse_args()

    entries = fetch_news_live(args.ticker, args.company)
    added = save_news(args.ticker, entries)
    print(f"{args.ticker}: fetched {len(entries)} headlines, {added} new")


if __name__ == "__main__":
    main()
