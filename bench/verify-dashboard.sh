#!/usr/bin/env sh
# Verify dashboard and all API endpoints from inside the Docker network.
# Run: docker run --rm --network tcad_mesh_mesh -v .../bench:/bench --entrypoint sh <image> /bench/verify-dashboard.sh

echo "=== 1. Dashboard HTML (checking for root div) ==="
HTML=$(wget -q -O - http://dashboard:3000 2>/dev/null)
echo "$HTML" | grep -o 'id="root"' | head -1

echo ""
echo "=== 2. JS Bundle URL and response ==="
JS_URL=$(echo "$HTML" | grep -o '/assets/[^"]*\.js' | head -1)
echo "JS URL: $JS_URL"
HTTP_CODE=$(wget -q -O /dev/null --server-response "http://dashboard:3000$JS_URL" 2>&1 | grep "HTTP/" | tail -1)
echo "JS HTTP: $HTTP_CODE"

echo ""
echo "=== 3. GET /honeytokens — must return objects not strings ==="
HT=$(wget -q -O - http://control-api:8003/honeytokens 2>/dev/null)
echo "$HT" | head -c 400
echo ""
SHAPE=$(echo "$HT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
tokens = d.get('tokens', [])
if not tokens:
    print('EMPTY')
elif isinstance(tokens[0], dict):
    print('OBJECTS (correct)')
else:
    print('STRINGS (bug)')
" 2>/dev/null || echo "PARSE_ERROR")
echo "Shape: $SHAPE"

echo ""
echo "=== 4. GET /stats ==="
wget -q -O - http://control-api:8003/stats 2>/dev/null | head -c 200
echo ""

echo ""
echo "=== 5. GET /events (first 3) ==="
wget -q -O - "http://control-api:8003/events?limit=3" 2>/dev/null | head -c 300
echo ""

echo ""
echo "=== 6. GET /quarantine ==="
wget -q -O - http://control-api:8003/quarantine 2>/dev/null | head -c 200
echo ""

echo ""
echo "=== 7. Dashboard /stats proxy ==="
wget -q -O - "http://dashboard:3000/stats" 2>/dev/null | head -c 200
echo ""

echo ""
echo "=== 8. Trigger sim and verify HT panel data ==="
# Trigger a canary → quarantine → honeypot response with honeytoken
wget -q -O /dev/null http://gateway:8080/admin -H "X-Device-ID: verify-dash-A" 2>/dev/null || true
sleep 0.5
HT_RESP=$(wget -q -O - http://gateway:8080/api/v1/shipments -H "X-Device-ID: verify-dash-A" 2>/dev/null)
TOKEN=$(echo "$HT_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data'][0]['id'] if d.get('data') else 'NONE')" 2>/dev/null || echo "NONE")
echo "Honeypot token: $TOKEN"
sleep 2
HT_LIST=$(wget -q -O - http://control-api:8003/honeytokens 2>/dev/null)
echo "Tokens in control-api: $(echo "$HT_LIST" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('tokens',[])), 'tokens')" 2>/dev/null)"

echo ""
echo "=== DONE ==="
