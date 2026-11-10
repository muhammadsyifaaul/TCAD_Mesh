# TCAD Mesh — Live Demo Script

**Duration:** ~8 minutes  
**Audience:** Hackathon judges  
**Prerequisites:** `docker compose up --build -d` completed, all services healthy.  
**Browser:** Open `http://localhost:3000` (dashboard)  
**Terminal:** Split view — left: curl commands; right: `docker compose logs -f gateway`

---

## Setup Checklist (Before Demo Starts)

- [ ] `docker compose up --build -d` — confirm all 5 services show `healthy`
- [ ] Browser open at `http://localhost:3000`
- [ ] Terminal ready with repo root as working directory
- [ ] `.env` has `TARPIT_DELAY_MS=3000` (default — shows visible delay)
- [ ] Clear any existing quarantine state: leave as-is (real events make it look live)

---

## Minute 0:00–1:00 — Introduction

**Say:** "TCAD Mesh is a transparent active-defense gateway. You deploy it in
front of your existing API. Your backend sees zero changes. Your legitimate
clients see zero changes. But an attacker sees a maze."

**Show:** The dashboard home page. Point out the Stats Panel (all zeros — clean slate).

---

## Minute 1:00–2:30 — Legitimate Traffic (Baseline)

**Say:** "First, let's establish that normal clients work perfectly."

```bash
# Legit client — should return real shipment data
curl -s http://localhost:8080/api/v1/shipments \
     -H "X-Device-ID: demo-legit-client" | python -m json.tool | head -20
```

**Show:** Response is real logistics data. Dashboard shows NO new alerts.

```bash
# Multiple legit requests
for path in /health /api/v1/shipments /api/v1/manifests /api/v1/routes; do
  code=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost:8080$path \
         -H "X-Device-ID: demo-legit-client")
  echo "$path → $code"
done
```

**Show:** All 200s. Dashboard Stats Panel still shows 0 alerts. Point out: **"Measured 0.0% false-positive rate."**

---

## Minute 2:30–4:00 — Canary Path Detection

**Say:** "Now let's see what happens when an attacker probes for `/admin`."

```bash
curl -v http://localhost:8080/admin \
     -H "X-Device-ID: demo-attacker-01" 2>&1 | grep -E "< HTTP|Server:"
```

**Show:** 
- The response is **200 OK** — the attacker thinks they found something
- `Server: nginx` header (normalised — identical to real backend)
- Dashboard Event Timeline: `CANARY_HIT` + `QUARANTINED` events appear immediately

**Say:** "The attacker got a 200 response — they think they've found the admin panel.
But they've actually been silently quarantined and redirected to our honeypot."

```bash
# Show attacker is now quarantined — subsequent requests also go to honeypot
curl -s http://localhost:8080/api/v1/shipments \
     -H "X-Device-ID: demo-attacker-01" | python -m json.tool | head -10
```

**Say:** "Every request from this identity, even to valid API paths, now returns
honeypot data. The data looks real — same schema, same ID formats — but it's
completely fictitious and laced with tracking tokens."

---

## Minute 4:00–5:30 — Honeytoken Lacing and Reuse

**Say:** "The attacker is now quarantined. Every request they make goes to the
honeypot. Let's capture a honeytoken from the honeypot response."

**IMPORTANT:** The attacker must be quarantined FIRST (e.g. by hitting /admin)
before requesting /api/v1/shipments. A fresh identity gets real data from
target-app — only a quarantined identity gets honeypot data with honeytokens.

```bash
# Step 1: Quarantine the attacker via canary path
curl -sf -o /dev/null http://localhost:8080/admin \
     -H "X-Device-ID: demo-attacker-02"
echo "Attacker quarantined via /admin canary"

# Step 2: Now the quarantined attacker requests /api/v1/shipments → honeypot data
# Extract a honeytoken from the honeypot response
TOKEN=$(curl -s http://localhost:8080/api/v1/shipments \
             -H "X-Device-ID: demo-attacker-02" | \
        python -c "import sys,json; print(json.load(sys.stdin)['data'][0]['id'])")
echo "Captured honeytoken from honeypot: $TOKEN"
```

**Show:** Dashboard Honeytoken Panel now shows this token as ACTIVE (may take ~2s
for gateway to poll the honeytoken list from control-api).

```bash
# Step 3: Wait for the gateway to poll the honeytoken list (~2s)
sleep 3

# Step 4: A DIFFERENT identity uses the captured token in a request
# The gateway scans the URI for known honeytokens → HONEYTOKEN_REUSED fires
curl -sf -o /dev/null "http://localhost:8080/api/v1/shipments?doc=$TOKEN" \
     -H "X-Device-ID: demo-attacker-03" -w "%{http_code}\n"
```

**Show:** Dashboard — `HONEYTOKEN_REUSED` event fires. The new identity is quarantined.

**Say:** "The gateway detected that someone used data that only exists in the honeypot.
That's attribution — we know this identity interacted with our trap."

---

## Minute 5:30–7:00 — Enumeration and Tarpit

**Say:** "Let's simulate a directory-busting scanner."

```bash
# 7 rapid 404 requests — triggers ENUM_DETECTED
for i in $(seq 1 7); do
  curl -sf -o /dev/null "http://localhost:8080/api/v$i/secret" \
       -H "X-Device-ID: demo-scanner-01" || true
done
```

**Show:** Dashboard — `ENUM_DETECTED` and `TARPIT_ACTIVE` events fire after the threshold.

```bash
# Now observe the tarpit delay — this request will hang for 3 seconds
time curl -sf -o /dev/null "http://localhost:8080/api/v8/more-scanning" \
          -H "X-Device-ID: demo-scanner-01"
```

**Say:** "Three-second delay per request. The scanner slows to a crawl. And if 50+ scanners
flood us simultaneously, they start getting 429 responses immediately."

---

## Minute 7:00–8:00 — Operator Dashboard + Release

**Say:** "The dashboard gives operators full visibility and control."

**Show in browser:**
1. **Stats Panel** — total events, active quarantines count
2. **Event Timeline** — filter to `CANARY_HIT`, show chronological feed
3. **Quarantine Table** — identities with TTL countdown
4. Click **Release** on one identity — watch it disappear within 2 seconds

**Say:** "Release propagates to the gateway in under 2 seconds via the polling loop.
Operators can also click 'Run Simulation' to replay this whole scenario on demand."

```bash
# Click Full Demo button in dashboard — or run via CLI:
curl -sX POST http://localhost:3000/sim/run \
     -H "Content-Type: application/json" \
     -d '{"scenario":"full"}'
```

**Show:** Events populate in real-time in the dashboard timeline.

---

## Closing (30 seconds)

**Say:** "TCAD Mesh turns your API into an active trap. Attackers get misleading data,
get tracked via honeytokens, get slowed by tarpits, and get quarantined — all while
legitimate users see nothing different. One `docker compose up` to deploy."

---

## Backup Commands (if something fails)

```bash
# Reset all demo data via the dashboard button, or via API:
curl -sX POST http://localhost:3000/reset -H "X-Internal-Key: dummy"

# Reset all state (stop, clean volumes, restart)
docker compose down -v && docker compose up --build -d

# Check service health
docker compose ps

# View gateway logs
docker compose logs gateway --tail=50

# Manually release all quarantines via control-api
IKEY=$(grep '^INTERNAL_KEY=' .env | cut -d= -f2-)
curl -sf http://localhost:3000/quarantine | \
  python -c "
import sys,json,subprocess
for e in json.load(sys.stdin)['data']:
    subprocess.run(['curl','-sX','POST',
      'http://localhost:3000/quarantine/' + e['identity'] + '/release'])
"
```
