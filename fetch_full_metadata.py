import json, os, time, requests

TOKEN = os.environ['DISCOGS_TOKEN']
HEADERS = {'Authorization': f'Discogs token={TOKEN}', 'User-Agent': 'CarnaticDiscography/1.0'}

with open('carnatic_discogs_1917_1953.json') as f:
    records = json.load(f)

# Resume support: check for partial results
output_file = 'carnatic_discogs_full.json'
fetched = {}
if os.path.exists(output_file):
    with open(output_file) as f:
        fetched_list = json.load(f)
    fetched = {r['id']: r for r in fetched_list}
    print(f"Resuming: {len(fetched)} already fetched")

total = len(records)
for i, rec in enumerate(records):
    rid = rec['id']
    if rid in fetched:
        continue
    
    url = f"https://api.discogs.com/releases/{rid}"
    try:
        resp = requests.get(url, headers=HEADERS)
        if resp.status_code == 429:
            wait = int(resp.headers.get('Retry-After', 60))
            print(f"  Rate limited, waiting {wait}s...")
            time.sleep(wait)
            resp = requests.get(url, headers=HEADERS)
        
        if resp.status_code == 200:
            data = resp.json()
            # Store search-level data plus full metadata
            rec['tracklist'] = data.get('tracklist', [])
            rec['identifiers'] = data.get('identifiers', [])
            rec['notes'] = data.get('notes', '')
            rec['artists_full'] = data.get('artists', [])
            rec['extraartists'] = data.get('extraartists', [])
            rec['labels_full'] = data.get('labels', [])
            rec['companies'] = data.get('companies', [])
            fetched[rid] = rec
        else:
            print(f"  Error {resp.status_code} for {rid}")
    except Exception as e:
        print(f"  Exception for {rid}: {e}")
    
    if (i + 1) % 50 == 0:
        print(f"Progress: {len(fetched)}/{total}")
        with open(output_file, 'w') as f:
            json.dump(list(fetched.values()), f)
    
    time.sleep(1.1)

# Final save
with open(output_file, 'w') as f:
    json.dump(list(fetched.values()), f)

print(f"\nDone! Fetched {len(fetched)}/{total} releases")
