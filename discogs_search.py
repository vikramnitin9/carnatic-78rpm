#!/usr/bin/env python3
"""Search Discogs for matching releases for carnatic 78rpm records."""

import json
import re
import time
import sys
import urllib.request
import urllib.parse
import urllib.error

HEADERS = {"User-Agent": "CarnaticRecordsProject/1.0"}
RETRY_WAIT = 60
MIN_DELAY = 4.0  # 15 req/min max, well under 25 unauthenticated limit

last_request_time = 0

def api_get(url, retries=2):
    """Make a GET request to Discogs API with rate limiting."""
    global last_request_time
    # Enforce minimum delay between requests
    elapsed = time.time() - last_request_time
    if elapsed < MIN_DELAY:
        time.sleep(MIN_DELAY - elapsed)
    last_request_time = time.time()

    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"    Rate limited, waiting {RETRY_WAIT}s...", flush=True)
                time.sleep(RETRY_WAIT)
                last_request_time = time.time()
                continue
            elif e.code == 404:
                return None
            else:
                print(f"    HTTP {e.code} for {url}", flush=True)
                if attempt < retries:
                    time.sleep(5)
                    continue
                return None
        except Exception as e:
            print(f"    Error: {e}", flush=True)
            if attempt < retries:
                time.sleep(5)
                continue
            return None
    return None


def normalize_name(name):
    """Normalize a performer name for loose comparison."""
    name = name.upper()
    # Remove parenthetical info like (Tamil), (Telugu), (Madras), etc.
    name = re.sub(r'\([^)]*\)', '', name)
    # Remove common titles/prefixes
    name = re.sub(r'\b(MISS|MR|MRS|SRI|SHRI|SRIMATHI|BRAHMA|DHAHINA|BHAGAVATHAR|VIDWAN|VIDUSHI)\b', '', name)
    # Remove punctuation
    name = re.sub(r'[^A-Z\s]', '', name)
    # Collapse whitespace
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def names_match_loosely(our_performer, discogs_artist):
    """Check if performer names match loosely."""
    our = normalize_name(our_performer)
    theirs = normalize_name(discogs_artist)

    if not our or not theirs:
        return True  # If we can't parse names, don't reject on name alone

    # Split into words
    our_words = set(our.split())
    their_words = set(theirs.split())

    if not our_words or not their_words:
        return True

    # Check if any significant word matches
    # Remove very short words (< 3 chars) for matching
    our_sig = {w for w in our_words if len(w) >= 3}
    their_sig = {w for w in their_words if len(w) >= 3}

    if not our_sig or not their_sig:
        return True

    # At least one significant word in common
    common = our_sig & their_sig
    if common:
        return True

    # Check for substring matches (e.g., NARAYANASWAMI vs NARAYANA)
    for ow in our_sig:
        for tw in their_sig:
            if len(ow) >= 4 and len(tw) >= 4:
                if ow in tw or tw in ow:
                    return True

    return False


def issue_matches_catno(issue, catno):
    """Check if our issue number matches a catalog number exactly."""
    if not catno:
        return False
    # Normalize both
    catno_clean = catno.strip()
    issue_clean = issue.strip()

    # Direct match
    if catno_clean == issue_clean:
        return True

    # Case-insensitive
    if catno_clean.upper() == issue_clean.upper():
        return True

    # Sometimes catno has spaces instead of hyphens or vice versa
    catno_norm = re.sub(r'[\s\-]+', '-', catno_clean)
    issue_norm = re.sub(r'[\s\-]+', '-', issue_clean)
    if catno_norm == issue_norm:
        return True

    # Handle G.C. prefix: "G.C.-3-13305" should match "3-13305"
    gc_match = re.match(r'G\.?\s*C\.?\s*[\-\.]\s*(.+)', catno_clean, re.I)
    if gc_match:
        catno_suffix = gc_match.group(1).strip()
        if catno_suffix == issue_clean:
            return True
        catno_suffix_norm = re.sub(r'[\s\-]+', '-', catno_suffix)
        if catno_suffix_norm == issue_norm:
            return True

    return False


def issue_matches_identifier(issue, identifier_value):
    """Check if our issue number appears in an identifier value, with false positive prevention."""
    if not identifier_value:
        return False

    val = identifier_value.strip()
    issue_clean = issue.strip()

    # Direct exact match
    if val == issue_clean:
        return True

    # Check for G.C.- prefix pattern
    gc_match = re.match(r'G\.?\s*C\.?\s*[\-\.]\s*(.+)', val, re.I)
    if gc_match:
        suffix = gc_match.group(1).strip()
        if suffix == issue_clean:
            return True
        suffix_norm = re.sub(r'[\s\-]+', '-', suffix)
        issue_norm = re.sub(r'[\s\-]+', '-', issue_clean)
        if suffix_norm == issue_norm:
            return True

    # CRITICAL: prevent false positives like "5-013012" matching "013012"
    # Only match if the issue appears as a complete segment
    # E.g., issue "013012" should NOT match identifier "5-013012"
    # But issue "3-13305" SHOULD match identifier "3-13305"

    # If the value contains our issue as a substring, check boundaries
    if issue_clean in val:
        # Find position
        idx = val.find(issue_clean)
        before = val[:idx]
        after = val[idx + len(issue_clean):]

        # Before should be empty, or end with G.C.- type prefix, or be just whitespace
        # It should NOT be another number prefix like "5-"
        if before:
            before = before.rstrip()
            # OK if it's a G.C. prefix
            if re.match(r'^G\.?\s*C\.?\s*[\-\.]?\s*$', before, re.I):
                return True
            # NOT OK if it ends with a digit followed by separator (like "5-")
            if re.match(r'.*\d[\s\-\.]+$', before):
                return False
            # NOT OK if it ends with a digit directly
            if before and before[-1].isdigit():
                return False
            # If before is just whitespace/separator, that's ok only if issue itself has no prefix
            if re.match(r'^[\s\-\.]+$', before):
                return True

        # After should be empty or just whitespace/separator
        if after and after.strip() and after.strip()[0].isdigit():
            return False

        if not before or before.isspace():
            return True

    return False


def check_release(release_url, issue, performer):
    """Fetch release details and check for matching issue number and performer."""
    data = api_get(release_url)
    if not data:
        return False

    # Check artist name
    artists = data.get('artists', [])
    artist_names = [a.get('name', '') for a in artists]
    artist_str = ' '.join(artist_names)

    # Also check extraartists
    extra_artists = data.get('extraartists', [])
    extra_names = [a.get('name', '') for a in extra_artists]
    artist_str += ' ' + ' '.join(extra_names)

    # Check labels catno
    labels = data.get('labels', [])
    for label in labels:
        catno = label.get('catno', '')
        if issue_matches_catno(issue, catno):
            if names_match_loosely(performer, artist_str):
                return True

    # Check identifiers
    identifiers = data.get('identifiers', [])
    for ident in identifiers:
        val = ident.get('value', '')
        if issue_matches_identifier(issue, val):
            if names_match_loosely(performer, artist_str):
                return True

    return False


def pre_filter_result(result, issue):
    """Quick pre-filter using search result data before fetching full release."""
    catno = result.get('catno', '')
    # If catno matches exactly, worth checking
    if issue_matches_catno(issue, catno):
        return True
    # If catno is similar (contains our number), also check
    # Extract numeric part of issue for substring check
    issue_digits = re.sub(r'[^0-9]', '', issue)
    catno_clean = catno.replace(' ', '')
    if issue_digits and len(issue_digits) >= 4 and issue_digits in catno_clean:
        return True
    # Also check the title field from search results
    title = result.get('title', '')
    if issue in title:
        return True
    # Check format descriptions
    for fmt in result.get('format', []):
        if issue in fmt:
            return True
    # If catno doesn't relate at all, still check (catno in search results may be incomplete)
    # But only for first 3 results to save API calls
    return None  # Signal: "maybe, use position limit"


def search_discogs(issue, performer):
    """Search Discogs for a matching release."""
    query = urllib.parse.quote(issue)
    url = f"https://api.discogs.com/database/search?q={query}&type=release&country=India"

    data = api_get(url)
    if not data or 'results' not in data:
        return None

    results = data.get('results', [])
    if not results:
        return None

    # Check each result with smart filtering
    maybe_count = 0
    checked = 0
    for result in results[:5]:
        release_id = result.get('id')
        if not release_id:
            continue

        pf = pre_filter_result(result, issue)
        if pf is True:
            # Definite candidate - check it
            pass
        elif pf is None:
            # Maybe - limit how many we check
            maybe_count += 1
            if maybe_count > 1:
                continue
        else:
            continue

        checked += 1
        if checked > 3:
            break

        release_url = f"https://api.discogs.com/releases/{release_id}"
        if check_release(release_url, issue, performer):
            return f"https://www.discogs.com/release/{release_id}"

    return None


def main():
    # Read index.html
    with open('index.html', 'r') as f:
        content = f.read()

    # Extract records
    match = re.search(r'var RECORDS = (.+?);\n\nvar tbody', content, re.DOTALL)
    if not match:
        print("ERROR: Could not find RECORDS in index.html")
        sys.exit(1)

    records = json.loads(match.group(1))
    total = len(records)
    print(f"Total records: {total}")
    print(f"Records without discogs: {sum(1 for r in records if not r.get('discogs'))}")
    print(f"Records with discogs: {sum(1 for r in records if r.get('discogs'))}")
    print()
    sys.stdout.flush()

    # Track new matches
    new_matches = []
    # Track which issues we've already searched (many records share issue numbers)
    searched_issues = {}  # issue -> discogs_url or None
    processed = 0

    for i, record in enumerate(records):
        processed += 1
        issue = record.get('issue', '').strip()
        performer = record.get('performer', '')

        if record.get('discogs'):
            print(f"[{processed}/{total}] Issue {issue}: Skipped (already has Discogs)")
            sys.stdout.flush()
            continue

        if not issue:
            print(f"[{processed}/{total}] No issue number, skipping")
            sys.stdout.flush()
            continue

        # Check if we already searched this issue
        if issue in searched_issues:
            cached = searched_issues[issue]
            if cached:
                print(f"[{processed}/{total}] Issue {issue}: Cached match: {cached}")
                new_matches.append((i, issue, performer, cached))
            else:
                print(f"[{processed}/{total}] Issue {issue}: Cached - no match")
            sys.stdout.flush()
            continue

        print(f"[{processed}/{total}] Issue {issue}: Searching...", end=" ", flush=True)

        discogs_url = search_discogs(issue, performer)

        if discogs_url:
            print(f"Found match: {discogs_url}")
            new_matches.append((i, issue, performer, discogs_url))
            searched_issues[issue] = discogs_url
        else:
            print("No match")
            searched_issues[issue] = None

        sys.stdout.flush()

        # Progress summary every 50 records
        if processed % 50 == 0:
            print(f"\n=== Progress: {processed}/{total} done, {len(new_matches)} new matches found so far ===\n")
            sys.stdout.flush()

    # Final summary
    print(f"\n{'='*60}")
    print(f"SEARCH COMPLETE")
    print(f"{'='*60}")
    print(f"Total records processed: {processed}")
    print(f"New Discogs matches found: {len(new_matches)}")
    print()

    if new_matches:
        print("New matches:")
        for idx, issue, performer, url in new_matches:
            print(f"  Record #{idx}: issue={issue}, performer={performer}")
            print(f"    -> {url}")
        print()

        # Update records
        for idx, issue, performer, url in new_matches:
            records[idx]['discogs'] = url

        # Write back to index.html
        new_json = json.dumps(records, ensure_ascii=False)
        new_content = content[:match.start(1)] + new_json + content[match.end(1):]

        with open('index.html', 'w') as f:
            f.write(new_content)

        print(f"Updated index.html with {len(new_matches)} new Discogs links.")

        # Save matches to a separate file for reference
        with open('new_discogs_matches.json', 'w') as f:
            json.dump([{"record_index": idx, "issue": issue, "performer": performer, "discogs": url}
                       for idx, issue, performer, url in new_matches], f, indent=2)
        print("Saved match details to new_discogs_matches.json")
    else:
        print("No new matches found.")

    sys.stdout.flush()


if __name__ == '__main__':
    main()
