#!/usr/bin/env python3
"""Fetch all 78 RPM (Shellac) recordings from India (1917-1953) from Discogs API.

Queries year-by-year, paginating through all results at 100/page.
Fetches full release details for each result.
Requires DISCOGS_TOKEN environment variable.
"""

import json
import time
import os
import urllib.request
import urllib.error

TOKEN = os.environ.get("DISCOGS_TOKEN", "")
HEADERS = {
    "User-Agent": "CarnaticRecordsProject/1.0",
    "Authorization": f"Discogs token={TOKEN}",
}
OUTPUT_FILE = "india_records_1917_1953.json"
MIN_DELAY = 1.0
MAX_RETRIES = 3


def api_get(url, retries=MAX_RETRIES):
    time.sleep(MIN_DELAY)
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            if attempt < retries:
                wait = 15 * (attempt + 1)
                print(f"  Retry {attempt+1}/{retries} after {wait}s: {e}")
                time.sleep(wait)
            else:
                raise


def fetch_year(year):
    """Fetch all search results for a given year, paginating."""
    results = []
    page = 1
    while True:
        url = (
            f"https://api.discogs.com/database/search?"
            f"type=release&country=India&format=Shellac"
            f"&year={year}&per_page=100&page={page}"
        )
        data = api_get(url)
        items = data.get("results", [])
        results.extend(items)
        pagination = data.get("pagination", {})
        total_pages = pagination.get("pages", 1)
        if page >= total_pages:
            break
        page += 1
    return results


def main():
    if not TOKEN:
        print("Error: DISCOGS_TOKEN environment variable not set")
        return

    all_releases = []
    seen_ids = set()

    for year in range(1917, 1954):
        results = fetch_year(year)
        new = 0
        for r in results:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                all_releases.append({
                    "id": r["id"],
                    "title": r.get("title", ""),
                    "year": r.get("year", ""),
                    "country": r.get("country", ""),
                    "catno": r.get("catno", ""),
                    "label": r.get("label", []),
                    "format": r.get("format", []),
                    "genre": r.get("genre", []),
                    "style": r.get("style", []),
                    "resource_url": r.get("resource_url", ""),
                    "uri": r.get("uri", ""),
                    "thumb": r.get("thumb", ""),
                })
                new += 1
        if new > 0:
            print(f"{year}: {new} releases (cumulative: {len(all_releases)})")

    print(f"\nTotal unique releases: {len(all_releases)}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_releases, f, indent=2, ensure_ascii=False)
    print(f"Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
