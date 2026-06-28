"""Market Consensus — Phase 1 entry point.

Runs every configured scraper and prints the normalized records in a clean,
human-readable format. Later phases will swap the print step for Supabase
storage and Claude-based sentiment extraction.
"""

from scrapers import news, reddit

SCRAPERS = {
    "reddit": reddit.scrape,
    "news": news.scrape,
}


def run_all():
    """Run every scraper and return a single combined list of records."""
    all_records = []
    for name, scrape_fn in SCRAPERS.items():
        print(f"Running scraper: {name} ...")
        try:
            records = scrape_fn()
            print(f"  -> {len(records)} records")
            all_records.extend(records)
        except Exception as exc:  # keep one bad source from killing the run
            print(f"  !! {name} failed: {exc}")
    return all_records


def print_records(records):
    """Pretty-print records to the terminal."""
    print(f"\n{'=' * 70}")
    print(f"COLLECTED {len(records)} RECORDS")
    print(f"{'=' * 70}\n")

    for i, record in enumerate(records, start=1):
        title = record["title"]
        snippet = record["text"].replace("\n", " ").strip()
        if len(snippet) > 200:
            snippet = snippet[:200] + "..."

        print(f"[{i:>3}] {record['source']}  ({record['timestamp']})")
        print(f"      {title}")
        if snippet and snippet != title:
            print(f"      {snippet}")
        print(f"      {record['url']}")
        print()


def main():
    records = run_all()
    print_records(records)


if __name__ == "__main__":
    main()
