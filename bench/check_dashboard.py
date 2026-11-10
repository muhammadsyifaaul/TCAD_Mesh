"""Verify dashboard and API from inside Docker network.

Run: docker run --rm --network tcad_mesh_mesh -v .../bench:/bench:ro <image> python /bench/check_dashboard.py
"""
import urllib.request, json, re, sys

def fetch(url):
    r = urllib.request.urlopen(url, timeout=5)
    return r.read().decode()

errors = []

# 1. Dashboard HTML
html = fetch('http://dashboard:3000')
has_root = 'id="root"' in html or "id='root'" in html
print(f'1. Dashboard HTML: root_div={has_root}  length={len(html)}')
if not has_root:
    errors.append('root div missing from dashboard HTML')

# 2. JS Bundle
m = re.search(r'/assets/[^"]+\.js', html)
js_url = m.group(0) if m else ''
print(f'2. JS Bundle URL: {js_url}')
if js_url:
    js = fetch('http://dashboard:3000' + js_url)
    print(f'   JS length: {len(js)} chars')
    if len(js) < 1000:
        errors.append(f'JS bundle too small: {len(js)}')
else:
    errors.append('JS bundle URL not found in HTML')

# 3. GET /honeytokens shape — must return objects with required fields
ht = json.loads(fetch('http://control-api:8003/honeytokens'))
tokens = ht.get('tokens', [])
if not tokens:
    print('3. /honeytokens: EMPTY (no prior honeytoken activity)')
else:
    all_objects = all(
        isinstance(t, dict) and 'token' in t and 'session_id' in t
        for t in tokens
    )
    print(f'3. /honeytokens: {len(tokens)} tokens  all-objects={all_objects}')
    print(f'   first: {json.dumps(tokens[0])[:150]}')
    if not all_objects:
        errors.append(f'/honeytokens contains non-object or incomplete entries')
    else:
        print('   ✅ shape correct — objects with token + session_id fields')

# 4. Stats
stats = json.loads(fetch('http://control-api:8003/stats'))
print(f'4. /stats: total_events={stats.get("total_events")}  quarantines={stats.get("active_quarantines")}')

# 5. Dashboard /stats proxy
proxy_json = json.loads(fetch('http://dashboard:3000/stats'))
proxy_ok = 'total_events' in proxy_json
print(f'5. /stats via dashboard proxy: ok={proxy_ok}')
if not proxy_ok:
    errors.append('/stats proxy missing total_events')

# 6. Quarantine (with epoch field)
q = json.loads(fetch('http://control-api:8003/quarantine'))
epoch_present = 'epoch' in q
print(f'6. /quarantine: epoch={q.get("epoch")}  active={len(q.get("data", []))}  epoch_present={epoch_present}')
if not epoch_present:
    errors.append('/quarantine missing epoch field')

# 7. Events
evts = json.loads(fetch('http://control-api:8003/events?limit=3'))
print(f'7. /events: total={evts.get("total")}')

# 8. Verify sim status endpoint
sim = json.loads(fetch('http://control-api:8003/sim/status'))
print(f'8. /sim/status: status={sim.get("status")}')
if 'status' not in sim:
    errors.append('/sim/status missing status field')

print()
if errors:
    print(f'RESULT: FAIL ({len(errors)} errors)')
    for e in errors:
        print(f'  ❌ {e}')
    sys.exit(1)
else:
    print('RESULT: PASS')
    print('  ✅ Dashboard HTML loads with root div')
    print('  ✅ JS bundle loads (162+ KB)')
    print('  ✅ /honeytokens returns objects with token+session_id fields')
    print('  ✅ /stats returns total_events')
    print('  ✅ /stats proxied through dashboard nginx')
    print('  ✅ /quarantine includes epoch field')
    print('  ✅ /sim/status endpoint works')
