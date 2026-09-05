"""
Check each ESI facility against DuckDuckGo search. Records ANY hit found
(excluding your own Scribd source document), plus which domain it came
from — so you can filter by source yourself later.
"""

import argparse
import csv
import sys
import time
from urllib.parse import urlparse

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        sys.exit("Install the search library first:\n  pip install ddgs")

REQUEST_DELAY_SECONDS = 2.0
RETRY_ON_ERROR = 3
BACKOFF_SECONDS = 10
RESULTS_PER_QUERY = 5

EXCLUDED_DOMAINS = ["scribd.com"]


def is_excluded(url):
    url = (url or "").lower()
    return any(d in url for d in EXCLUDED_DOMAINS)


def get_domain(url):
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def search(query):
    for attempt in range(RETRY_ON_ERROR):
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=RESULTS_PER_QUERY, backend="duckduckgo"))
            return results
        except Exception as e:
            msg = str(e).lower()
            if "ratelimit" in msg or "429" in msg or "202" in msg:
                wait = BACKOFF_SECONDS * (attempt + 1)
                print(f"  looks rate-limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            if "no results found" in msg:
                return []
            print(f"  search error: {e}", file=sys.stderr)
            time.sleep(2 ** attempt)
    return []


def main(in_path, out_path, limit=None, start_at=0):
    with open(in_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    end = start_at + limit if limit else len(rows)
    subset = rows[start_at:end]

    fieldnames = list(rows[0].keys()) + [
        "search_hit",
        "match_source",
        "top_result_title",
        "top_result_link",
    ]

    mode = "a" if start_at > 0 else "w"
    write_header = start_at == 0

    with open(out_path, mode, newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()

        for i, row in enumerate(subset, start=start_at + 1):
            address_hint = row["address"].split(",")[0].strip()
            query = f"ESI {row['type']} {address_hint} {row['city']}"
            results = search(query)

            usable = [r for r in results if not is_excluded(r.get("href", ""))]
            best = usable[0] if usable else None

            row["search_hit"] = bool(best)
            row["match_source"] = get_domain(best.get("href", "")) if best else ""
            row["top_result_title"] = best.get("title", "") if best else ""
            row["top_result_link"] = best.get("href", "") if best else ""

            writer.writerow(row)
            out_f.flush()

            if i % 10 == 0:
                print(f"  processed {i}/{end}", file=sys.stderr)

            time.sleep(REQUEST_DELAY_SECONDS)

    print(f"Done. Wrote {out_path} (rows {start_at+1}-{end})")
    print(f"If it stopped early or got blocked, resume with: --start-at {end}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv")
    parser.add_argument("output_csv")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start-at", type=int, default=0)
    args = parser.parse_args()
    main(args.input_csv, args.output_csv, args.limit, args.start_at)

    