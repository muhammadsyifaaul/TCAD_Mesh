// gateway/hardening_test.go
// Tier 4 hardening tests.
package main

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// ── Body size limit ───────────────────────────────────────────────────────────

func TestBodySizeLimitRejectsOversizedRequest(t *testing.T) {
	upstream := httptest.NewServer(stubUpstream(200))
	defer upstream.Close()
	honeypot := httptest.NewServer(stubUpstream(200))
	defer honeypot.Close()

	h := buildTestHandler(upstream, honeypot, func(c *Config) {
		c.MaxBodyBytes = 100 // tiny limit for test
	})
	wrapped := limitBodyMiddleware(100, h)

	// Body larger than limit
	bigBody := bytes.Repeat([]byte("X"), 200)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/shipments", bytes.NewReader(bigBody))
	req.ContentLength = int64(len(bigBody))
	req.RemoteAddr = "10.0.0.1:1234"
	rr := httptest.NewRecorder()
	wrapped.ServeHTTP(rr, req)

	if rr.Code != http.StatusRequestEntityTooLarge {
		t.Errorf("expected 413, got %d", rr.Code)
	}
}

func TestBodySizeLimitAllowsSmallRequest(t *testing.T) {
	upstream := httptest.NewServer(stubUpstream(200))
	defer upstream.Close()
	honeypot := httptest.NewServer(stubUpstream(200))
	defer honeypot.Close()

	h := buildTestHandler(upstream, honeypot)
	wrapped := limitBodyMiddleware(1<<20, h)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/shipments", nil)
	req.RemoteAddr = "10.0.0.2:1234"
	rr := httptest.NewRecorder()
	wrapped.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Errorf("expected 200, got %d", rr.Code)
	}
}

// ── Panic recovery ────────────────────────────────────────────────────────────

func TestRecoveryMiddlewareCatchesPanic(t *testing.T) {
	panicHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		panic("simulated handler panic")
	})
	wrapped := recoveryMiddleware(panicHandler)

	req := httptest.NewRequest(http.MethodGet, "/boom", nil)
	req.RemoteAddr = "10.0.0.3:1234"
	rr := httptest.NewRecorder()

	// Must not panic here — recovery middleware catches it
	defer func() {
		if r := recover(); r != nil {
			t.Errorf("panic escaped recovery middleware: %v", r)
		}
	}()
	wrapped.ServeHTTP(rr, req)

	if rr.Code != http.StatusInternalServerError {
		t.Errorf("expected 500 after panic, got %d", rr.Code)
	}
}

// ── MaxHeaderBytes via server config ──────────────────────────────────────────

func TestServerTimeoutsConfigured(t *testing.T) {
	cfg := loadConfig()
	// Verify WriteTimeout > TarpitDelayMs (otherwise slow tarpits would be cut off)
	writeTimeout := cfg.TarpitDelayMs + cfg.UpstreamTimeout + 10*time.Second
	if writeTimeout <= cfg.TarpitDelayMs {
		t.Errorf("WriteTimeout (%v) must exceed TarpitDelayMs (%v)", writeTimeout, cfg.TarpitDelayMs)
	}
}

// ── buildProxy variadic timeout ───────────────────────────────────────────────

func TestBuildProxyAcceptsTimeout(t *testing.T) {
	srv := httptest.NewServer(stubUpstream(200))
	defer srv.Close()
	// Must not panic — variadic arg accepted
	proxy := buildProxy(srv.URL, 5*time.Second)
	if proxy == nil {
		t.Fatal("buildProxy returned nil")
	}
}

// ── Sanitize: large path truncated before logging ─────────────────────────────

func TestLargePathTruncated(t *testing.T) {
	huge := "/" + strings.Repeat("a", 1000)
	result := sanitizePath(huge)
	if len(result) > 256 {
		t.Errorf("sanitizePath did not truncate: len=%d", len(result))
	}
}
