// gateway/pipeline_test.go
// Table-driven tests for the detection pipeline (Gate T1 criteria).
// All tests use httptest stubs — no real network calls.
package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// ── Test fixtures ─────────────────────────────────────────────────────────────

// stubUpstream returns a handler that always responds with the given status.
func stubUpstream(status int) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_, _ = w.Write([]byte(`{"stub":true}`))
	})
}

// buildTestHandler creates a Handler wired against fake upstream/honeypot servers.
func buildTestHandler(
	upstreamSrv *httptest.Server,
	honeypotSrv *httptest.Server,
	overrides ...func(*Config),
) *Handler {
	cfg := Config{
		UpstreamURL:      upstreamSrv.URL,
		HoneypotURL:      honeypotSrv.URL,
		ControlURL:       "http://127.0.0.1:19999", // nothing listening — events dropped
		InternalKey:      "test-key",
		CanaryPaths:      map[string]struct{}{"/admin": {}, "/.env": {}, "/backup": {}},
		EnumThreshold:    3,
		EnumWindowSec:    10 * time.Second,
		TarpitDelayMs:    1 * time.Millisecond, // near-zero for tests
		TarpitMaxConc:    2,
		QuarantineTTLSec: 60 * time.Second,
		Mode2Enabled:     false,
	}
	for _, o := range overrides {
		o(&cfg)
	}

	h := &Handler{
		cfg:        cfg,
		quarantine: newQuarantineStore(),
		tokens:     newHoneytokenStore(),
		enum:       newEnumTracker(cfg.EnumThreshold, cfg.EnumWindowSec),
		tarpit:     newTarpit(cfg.TarpitMaxConc),
		dispatcher: newNoopDispatcher(), // no real HTTP in unit tests
		upstream:   buildProxy(cfg.UpstreamURL, 10*time.Second),
		honeypot:   buildProxy(cfg.HoneypotURL, 10*time.Second),
		ctrlClient: &http.Client{Timeout: 1 * time.Second},
		nonceStore: newMemNonceStore(), // always in-memory for unit tests
		nowFn:      time.Now,
	}
	return h
}

// ── 1. Legitimate request passes through to target-app ───────────────────────
func TestLegitRequestPassesThrough(t *testing.T) {
	upstream := httptest.NewServer(stubUpstream(200))
	defer upstream.Close()
	honeypot := httptest.NewServer(stubUpstream(200))
	defer honeypot.Close()

	h := buildTestHandler(upstream, honeypot)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/shipments", nil)
	req.RemoteAddr = "10.0.0.1:1234"
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rr.Code)
	}
}

// ── 2. Canary path → QUARANTINED + routed to honeypot ────────────────────────
func TestCanaryPathTriggersHoneypot(t *testing.T) {
	cases := []struct {
		name string
		path string
	}{
		{"admin", "/admin"},
		{"dotenv", "/.env"},
		{"backup", "/backup"},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			upstream := httptest.NewServer(stubUpstream(200))
			defer upstream.Close()

			honeypotHit := false
			honeypot := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				honeypotHit = true
				w.WriteHeader(200)
			}))
			defer honeypot.Close()

			h := buildTestHandler(upstream, honeypot)

			req := httptest.NewRequest(http.MethodGet, tc.path, nil)
			req.RemoteAddr = "10.0.0.2:1111"
			rr := httptest.NewRecorder()
			h.ServeHTTP(rr, req)

			if !honeypotHit {
				t.Errorf("honeypot not reached for canary path %s", tc.path)
			}
			// Identity should now be quarantined
			identity := stripPort(req.RemoteAddr)
			if !h.quarantine.IsQuarantined(identity) {
				t.Errorf("identity not quarantined after canary hit")
			}
		})
	}
}

// ── 3. Quarantined identity goes directly to honeypot (no upstream call) ─────
func TestQuarantinedIdentitySkipsUpstream(t *testing.T) {
	upstreamHit := false
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upstreamHit = true
		w.WriteHeader(200)
	}))
	defer upstream.Close()

	honeypot := httptest.NewServer(stubUpstream(200))
	defer honeypot.Close()

	h := buildTestHandler(upstream, honeypot)

	// Pre-quarantine the identity
	identity := "10.0.0.3"
	h.quarantine.Add(identity, "CANARY_HIT", 60*time.Second)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/shipments", nil)
	req.Header.Set("X-Device-ID", identity)
	req.RemoteAddr = "10.0.0.3:2222"
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, req)

	if upstreamHit {
		t.Error("upstream should NOT be called for quarantined identity")
	}
}

// ── 4. Subsequent requests after canary hit go directly to honeypot ──────────
func TestSubsequentRequestsAfterCanaryGoToHoneypot(t *testing.T) {
	upstream := httptest.NewServer(stubUpstream(200))
	defer upstream.Close()

	honeypotCalls := 0
	honeypot := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		honeypotCalls++
		w.WriteHeader(200)
	}))
	defer honeypot.Close()

	h := buildTestHandler(upstream, honeypot)
	identity := "device-attacker-99"

	// First request: canary hit
	req1 := httptest.NewRequest(http.MethodGet, "/admin", nil)
	req1.Header.Set("X-Device-ID", identity)
	req1.RemoteAddr = "10.1.1.1:9000"
	h.ServeHTTP(httptest.NewRecorder(), req1)

	// Second request: normal path but identity is quarantined
	req2 := httptest.NewRequest(http.MethodGet, "/api/v1/shipments", nil)
	req2.Header.Set("X-Device-ID", identity)
	req2.RemoteAddr = "10.1.1.1:9001"
	h.ServeHTTP(httptest.NewRecorder(), req2)

	if honeypotCalls < 2 {
		t.Errorf("expected both requests to hit honeypot, got %d honeypot calls", honeypotCalls)
	}
}

// ── 5. 404 enumeration sliding window → ENUM_DETECTED ────────────────────────
func TestEnumDetectionAfterThreshold(t *testing.T) {
	upstream := httptest.NewServer(stubUpstream(404))
	defer upstream.Close()
	honeypot := httptest.NewServer(stubUpstream(200))
	defer honeypot.Close()

	// threshold=3, so 4 requests should trigger ENUM_DETECTED
	h := buildTestHandler(upstream, honeypot, func(c *Config) {
		c.EnumThreshold = 3
		c.EnumWindowSec = 10 * time.Second
		c.TarpitDelayMs = 1 * time.Millisecond
	})

	identity := "scanner-device-01"
	var lastCode int
	for i := 0; i < 4; i++ {
		req := httptest.NewRequest(http.MethodGet, "/random/path/"+string(rune('a'+i)), nil)
		req.Header.Set("X-Device-ID", identity)
		req.RemoteAddr = "10.2.0.1:5000"
		rr := httptest.NewRecorder()
		h.ServeHTTP(rr, req)
		lastCode = rr.Code
	}

	// 4th request should have triggered tarpit (still gets 404 from upstream after delay)
	// The important assertion: enum tracker records the hit
	count, exceeded := h.enum.Record(identity, time.Now)
	if !exceeded {
		t.Errorf("expected enum threshold exceeded after 4 hits, count=%d", count)
	}
	_ = lastCode
}

// ── 6. Enum hits within window trigger tarpit; outside window do not ──────────
func TestEnumWindowResets(t *testing.T) {
	upstream := httptest.NewServer(stubUpstream(404))
	defer upstream.Close()
	honeypot := httptest.NewServer(stubUpstream(200))
	defer honeypot.Close()

	h := buildTestHandler(upstream, honeypot, func(c *Config) {
		c.EnumThreshold = 3
		c.EnumWindowSec = 1 * time.Second // tiny window for test
	})

	identity := "scanner-timeout"

	// 3 hits within window
	for i := 0; i < 3; i++ {
		req := httptest.NewRequest(http.MethodGet, "/path/x", nil)
		req.Header.Set("X-Device-ID", identity)
		req.RemoteAddr = "10.3.0.1:6000"
		h.ServeHTTP(httptest.NewRecorder(), req)
	}

	// Wait for window to expire
	time.Sleep(1100 * time.Millisecond)

	// New hit — counter should have reset (old hits pruned)
	count, exceeded := h.enum.Record(identity, time.Now)
	if exceeded {
		t.Errorf("enum counter should have expired, but still exceeded; count=%d", count)
	}
}

// ── 7. Tarpit semaphore full → 429 ───────────────────────────────────────────
func TestTarpitSaturatedReturns429(t *testing.T) {
	upstream := httptest.NewServer(stubUpstream(404))
	defer upstream.Close()
	honeypot := httptest.NewServer(stubUpstream(200))
	defer honeypot.Close()

	// maxConcurrent=1, threshold=1 so second tarpit request gets 429
	h := buildTestHandler(upstream, honeypot, func(c *Config) {
		c.EnumThreshold = 0 // every 404 triggers tarpit
		c.TarpitMaxConc = 1
		c.TarpitDelayMs = 500 * time.Millisecond
	})

	// Occupy the semaphore
	acquired := h.tarpit.TryAcquire()
	if !acquired {
		t.Fatal("semaphore should be acquirable initially")
	}
	// Do NOT release — simulate saturated tarpit

	// Now make a request that tries to acquire
	req := httptest.NewRequest(http.MethodGet, "/probing", nil)
	req.Header.Set("X-Device-ID", "saturated-device")
	req.RemoteAddr = "10.4.0.1:7000"
	rr := httptest.NewRecorder()

	// Manually trigger the post-404 tarpit path by pre-recording an enum hit
	identity := "saturated-device"
	for i := 0; i <= h.cfg.EnumThreshold; i++ {
		h.enum.Record(identity, time.Now)
	}

	// The next 404 should hit saturated tarpit → 429
	// We invoke the tarpit path directly since upstream stub returns 404
	h.ServeHTTP(rr, req)
	if rr.Code != http.StatusTooManyRequests {
		t.Errorf("expected 429 when tarpit saturated, got %d", rr.Code)
	}

	// Cleanup
	h.tarpit.Release()
}

// ── 8. Identity uses X-Device-ID header when present ─────────────────────────
func TestIdentityExtractionPrefersDeviceID(t *testing.T) {
	upstream := httptest.NewServer(stubUpstream(200))
	defer upstream.Close()
	honeypot := httptest.NewServer(stubUpstream(200))
	defer honeypot.Close()

	h := buildTestHandler(upstream, honeypot)

	deviceID := "device-explicit-42"
	h.quarantine.Add(deviceID, "test", 60*time.Second)

	// Request from different IP but with quarantined X-Device-ID
	req := httptest.NewRequest(http.MethodGet, "/api/v1/routes", nil)
	req.Header.Set("X-Device-ID", deviceID)
	req.RemoteAddr = "192.168.9.9:8888" // IP is NOT quarantined

	upstreamHit := false
	// Swap upstream to detect if it's called
	upstream2 := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upstreamHit = true
		w.WriteHeader(200)
	}))
	defer upstream2.Close()
	h.upstream = buildProxy(upstream2.URL)

	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, req)

	if upstreamHit {
		t.Error("upstream called despite X-Device-ID being quarantined; identity extraction failed")
	}
}

// ── 9. Header normalisation: Server=nginx, no X-Powered-By ────────────────
func TestHeaderNormalisation(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Powered-By", "uvicorn")
		w.Header().Set("Server", "uvicorn")
		w.WriteHeader(200)
		_, _ = w.Write([]byte(`{}`))
	}))
	defer upstream.Close()
	honeypot := httptest.NewServer(stubUpstream(200))
	defer honeypot.Close()

	h := buildTestHandler(upstream, honeypot)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/shipments", nil)
	req.RemoteAddr = "10.5.0.1:9999"
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, req)

	if got := rr.Header().Get("Server"); got != "nginx" {
		t.Errorf("expected Server: nginx, got %q", got)
	}
	if got := rr.Header().Get("X-Powered-By"); got != "" {
		t.Errorf("expected X-Powered-By to be stripped, got %q", got)
	}
}

// ── 10. Health endpoint returns 200 ──────────────────────────────────────────
func TestHealthEndpoint(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	rr := httptest.NewRecorder()
	healthHandler(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rr.Code)
	}
	var body map[string]any
	if err := json.Unmarshal(rr.Body.Bytes(), &body); err != nil {
		t.Fatalf("health response is not valid JSON: %v", err)
	}
	if body["status"] != "ok" {
		t.Errorf("expected status=ok, got %v", body["status"])
	}
}

// ── 11. Honeytoken in URI triggers HONEYTOKEN_REUSED + honeypot routing ──────
func TestHoneytokenInURITriggersHoneypot(t *testing.T) {
	upstreamHit := false
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upstreamHit = true
		w.WriteHeader(200)
	}))
	defer upstream.Close()

	honeypotHit := false
	honeypot := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		honeypotHit = true
		w.WriteHeader(200)
	}))
	defer honeypot.Close()

	h := buildTestHandler(upstream, honeypot)
	// Seed a honeytoken with full metadata (new contract)
	h.tokens.Replace([]HoneytokenEntry{{
		Token:     "DOC-aabbccddeeff",
		SessionID: "sess-original-issuer",
		Identity:  "original-victim",
		IssuedAt:  "2026-11-08T10:00:00Z",
	}})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/shipments?doc=DOC-aabbccddeeff", nil)
	req.Header.Set("X-Device-ID", "attacker-reuse-42")
	req.Header.Set("X-Session-ID", "sess-reuser")
	req.RemoteAddr = "10.9.0.1:1234"
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, req)

	if upstreamHit {
		t.Error("upstream should NOT be called when a honeytoken is present")
	}
	if !honeypotHit {
		t.Error("honeypot should be called on HONEYTOKEN_REUSED")
	}
	if !h.quarantine.IsQuarantined("attacker-reuse-42") {
		t.Error("identity not quarantined after honeytoken reuse")
	}
}

// ── 12. HoneytokenStore Replace + Lookup ─────────────────────────────────────
func TestHoneytokenStoreReplaceAndContains(t *testing.T) {
	ts := newHoneytokenStore()
	ts.Replace([]HoneytokenEntry{
		{Token: "DOC-111111111111", SessionID: "s1", Identity: "id1", IssuedAt: "2026-01-01T00:00:00Z"},
		{Token: "DOC-222222222222", SessionID: "s2", Identity: "id2", IssuedAt: "2026-01-01T00:00:00Z"},
	})
	if _, ok := ts.Lookup("DOC-111111111111"); !ok {
		t.Error("token should be present after Replace")
	}
	if _, ok := ts.Lookup("DOC-333333333333"); ok {
		t.Error("token should not be present")
	}
	// Replace with new set — old tokens gone
	ts.Replace([]HoneytokenEntry{{Token: "DOC-999999999999", SessionID: "s9", Identity: "id9", IssuedAt: "2026-01-01T00:00:00Z"}})
	if _, ok := ts.Lookup("DOC-111111111111"); ok {
		t.Error("old token should be gone after Replace")
	}
}
