// gateway/pipeline.go
// Core detection pipeline (AGENTS.md §4.3).
//
// Execution order per spec:
//   1. Identity Extraction
//   2. Quarantine Check      → proxy to honeypot, stop.
//   3. Honeytoken Scan       → quarantine + honeypot + HONEYTOKEN_REUSED event.
//   4. Canary Check          → quarantine + honeypot, stop.
//   5. Upstream Proxy        → buffer full response from target-app.
//   6. Enumeration Threshold → if 404 counter > threshold, activate tarpit.
//   7. Tarpit Execution      → sleep (semaphore bounded) or return 429.
//   8. Header Normalisation  → applied to ALL responses before flushing.
package main

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httputil"
	"strings"
	"time"
)

// Handler is the main HTTP handler that runs every request through the pipeline.
type Handler struct {
	cfg        Config
	quarantine *QuarantineStore
	tokens     *HoneytokenStore
	enum       *EnumTracker
	tarpit     *Tarpit
	dispatcher *Dispatcher
	upstream   *httputil.ReverseProxy
	honeypot   *httputil.ReverseProxy
	// internal HTTP client for control-api writes (quarantine registration)
	ctrlClient *http.Client
	// nonceStore: Redis-backed for Mode 2 anti-replay; in-memory fallback
	nonceStore NonceStore
	// nowFn is injectable for deterministic testing (AGENTS.md §5 anti-pattern guard)
	nowFn func() time.Time
}

func newHandler(cfg Config) *Handler {
	qs := newQuarantineStore()
	ts := newHoneytokenStore()
	return &Handler{
		cfg:        cfg,
		quarantine: qs,
		tokens:     ts,
		enum:       newEnumTracker(cfg.EnumThreshold, cfg.EnumWindowSec),
		tarpit:     newTarpit(cfg.TarpitMaxConc),
		dispatcher: newDispatcher(cfg.ControlURL, cfg.InternalKey),
		upstream:   buildProxy(cfg.UpstreamURL, cfg.UpstreamTimeout),
		honeypot:   buildProxy(cfg.HoneypotURL, cfg.UpstreamTimeout),
		ctrlClient: &http.Client{Timeout: 3 * time.Second},
		nonceStore: newNonceStore(cfg.RedisURL, cfg.Mode2Enabled),
		nowFn:      time.Now,
	}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// Calculate now() ONCE per request — AGENTS.md §5 anti-pattern guard
	// (never call time.Now() multiple times in a routing decision block)
	now := h.nowFn()

	// ── Step 0: Mode 2 routing (only when MODE2_ENABLED=true) ────────────────
	// Executed BEFORE all Mode 1 checks. When flag is false, this is a
	// single boolean check — zero performance impact on Mode 1 path.
	if h.cfg.Mode2Enabled {
		identity := sanitizeIdentity(r.Header.Get("X-Device-ID"))
		if identity == "" {
			identity = sanitizeIdentity(stripPort(r.RemoteAddr))
		}
		sessionID := r.Header.Get("X-Session-ID")
		if sessionID == "" {
			sessionID = identity
		}
		srcIP := r.RemoteAddr
		safeUA := sanitizeUA(r.Header.Get("User-Agent"))
		if h.handleMode2(w, r, identity, sessionID, srcIP, safeUA, now) {
			return
		}
		// handleMode2 returned false → path is not /m/ format.
		// When MODE2_STRICT=true (default), block direct access to upstream.
		if h.cfg.Mode2Strict {
			slog.Debug("mode2 strict: non-/m/ path blocked", "path", sanitizePath(r.URL.Path))
			writeJSON(w, http.StatusNotFound, `{"error":"not found","code":404}`)
			return
		}
		// When MODE2_STRICT=false, fall through to Mode 1 pipeline.
	}

	// ── Step 1: Identity Extraction ──────────────────────────────────────────
	identity := sanitizeIdentity(r.Header.Get("X-Device-ID"))
	if identity == "" {
		identity = sanitizeIdentity(stripPort(r.RemoteAddr))
	}
	sessionID := r.Header.Get("X-Session-ID")
	if sessionID == "" {
		sessionID = identity
	}
	srcIP := r.RemoteAddr

	safePath := sanitizePath(r.URL.RequestURI())
	safeUA := sanitizeUA(r.Header.Get("User-Agent"))
	method := r.Method

	// ── Step 2: Quarantine Check ─────────────────────────────────────────────
	if h.quarantine.IsQuarantined(identity) {
		slog.Debug("quarantined → honeypot", "identity", identity, "path", safePath)
		h.honeypot.ServeHTTP(w, r)
		return
	}

	// ── Step 3: Honeytoken Scan ───────────────────────────────────────────────
	// Scan request URI (+ headers + body) for any registered honeytoken.
	// Attribution: emit HONEYTOKEN_REUSED with:
	//   session_id = the REUSING request's session (current request)
	//   detail.original_session = the ISSUING session (looked up from HoneytokenStore)
	//   detail.original_identity = the ISSUING identity
	// This requires GET /honeytokens to return full objects (contract change in item 2).
	if entry, found := h.findHoneytoken(r); found {
		slog.Info("HONEYTOKEN_REUSED", "identity", identity, "token", entry.Token,
			"original_session", entry.SessionID, "path", safePath)
		h.quarantine.Add(identity, "HONEYTOKEN_REUSED", h.cfg.QuarantineTTLSec)
		h.dispatcher.Emit(newEvent("HONEYTOKEN_REUSED", "high",
			srcIP, identity, sessionID, method, safePath, safeUA,
			200, map[string]any{
				"token":             entry.Token,
				"original_session":  entry.SessionID,   // the issuing session
				"original_identity": entry.Identity,    // the issuing identity
			},
		))
		h.dispatcher.Emit(newEvent("QUARANTINED", "high",
			srcIP, identity, sessionID, method, safePath, safeUA,
			200, map[string]any{"reason": "HONEYTOKEN_REUSED", "ttl_sec": h.cfg.QuarantineTTLSec.Seconds()},
		))
		go h.notifyQuarantine(identity, "HONEYTOKEN_REUSED")
		h.honeypot.ServeHTTP(w, r)
		return
	}

	// ── Step 4: Canary Check ─────────────────────────────────────────────────
	if _, isCanary := h.cfg.CanaryPaths[r.URL.Path]; isCanary {
		slog.Info("CANARY_HIT", "identity", identity, "path", safePath, "ua", safeUA)
		h.quarantine.Add(identity, "CANARY_HIT", h.cfg.QuarantineTTLSec)
		h.dispatcher.Emit(newEvent("CANARY_HIT", "high",
			srcIP, identity, sessionID, method, safePath, safeUA,
			200, map[string]any{"canary_path": safePath},
		))
		h.dispatcher.Emit(newEvent("QUARANTINED", "high",
			srcIP, identity, sessionID, method, safePath, safeUA,
			200, map[string]any{"reason": "CANARY_HIT", "ttl_sec": h.cfg.QuarantineTTLSec.Seconds()},
		))
		go h.notifyQuarantine(identity, "CANARY_HIT")
		h.honeypot.ServeHTTP(w, r)
		return
	}

	// ── Step 5: Upstream Proxy — buffer full response ─────────────────────────
	buf := newBufferedResponseWriter()
	h.upstream.ServeHTTP(buf, r)
	upstreamStatus := buf.status

	// ── Step 6: Enumeration Threshold ────────────────────────────────────────
	if upstreamStatus == http.StatusNotFound {
		count, exceeded := h.enum.Record(identity, h.nowFn)
		slog.Debug("404 recorded", "identity", identity, "count", count, "path", safePath)

		if exceeded {
			slog.Info("ENUM_DETECTED → tarpit", "identity", identity, "404_count", count, "path", safePath)
			h.dispatcher.Emit(newEvent("ENUM_DETECTED", "warn",
				srcIP, identity, sessionID, method, safePath, safeUA,
				404, map[string]any{"count": count, "window_sec": h.cfg.EnumWindowSec.Seconds()},
			))

			// ── Step 7: Tarpit ────────────────────────────────────────────────
			if !h.tarpit.TryAcquire() {
				slog.Info("TARPIT_SATURATED → 429", "identity", identity)
				h.dispatcher.Emit(newEvent("TARPIT_SATURATED", "warn",
					srcIP, identity, sessionID, method, safePath, safeUA,
					429, nil,
				))
				writeJSON(w, http.StatusTooManyRequests, `{"error":"too many requests","code":429}`)
				return
			}
			h.dispatcher.Emit(newEvent("TARPIT_ACTIVE", "warn",
				srcIP, identity, sessionID, method, safePath, safeUA,
				404, map[string]any{"delay_ms": h.cfg.TarpitDelayMs.Milliseconds()},
			))
			time.Sleep(h.cfg.TarpitDelayMs)
			h.tarpit.Release()
		}
	}

	// ── Step 8: Header Normalisation + flush ─────────────────────────────────
	for k, vs := range buf.header {
		for _, v := range vs {
			w.Header().Set(k, v)
		}
	}
	w.Header().Set("Server", "nginx")
	w.Header().Del("X-Powered-By")
	if w.Header().Get("Date") == "" {
		w.Header().Set("Date", now.UTC().Format(http.TimeFormat))
	}
	w.WriteHeader(buf.status)
	_, _ = io.Copy(w, bytes.NewReader(buf.body.Bytes()))
}

// findHoneytoken scans the request URI, selected headers, and request body
// (up to a size limit) for any registered honeytoken.
// Returns the matching HoneytokenEntry and true, or (zero, false) if none found.
func (h *Handler) findHoneytoken(r *http.Request) (HoneytokenEntry, bool) {
	snapshot := h.tokens.Snapshot()
	if len(snapshot) == 0 {
		return HoneytokenEntry{}, false
	}

	// 1. URI (path + query)
	target := r.URL.RequestURI()
	for _, tok := range snapshot {
		if strings.Contains(target, tok) {
			if e, ok := h.tokens.Lookup(tok); ok {
				return e, true
			}
		}
	}

	// 2. Selected headers
	for _, hdr := range []string{"X-Device-ID", "X-Custom-Header", "Referer", "Cookie"} {
		val := r.Header.Get(hdr)
		if val == "" {
			continue
		}
		for _, tok := range snapshot {
			if strings.Contains(val, tok) {
				if e, ok := h.tokens.Lookup(tok); ok {
					return e, true
				}
			}
		}
	}

	// 3. Request body (limited to 64KB)
	if r.Body != nil && r.ContentLength != 0 {
		body, err := io.ReadAll(io.LimitReader(r.Body, 64*1024))
		if err == nil && len(body) > 0 {
			r.Body = io.NopCloser(strings.NewReader(string(body)))
			bodyStr := string(body)
			for _, tok := range snapshot {
				if strings.Contains(bodyStr, tok) {
					if e, ok := h.tokens.Lookup(tok); ok {
						return e, true
					}
				}
			}
		} else if err != nil {
			r.Body = io.NopCloser(strings.NewReader(""))
		}
	}

	return HoneytokenEntry{}, false
}

// notifyQuarantine POSTs a quarantine entry to control-api.
// On success, calls qs.Confirm() to mark the in-memory entry as confirmed,
// preventing the quarantine poller from releasing it before DB persistence.
// Called in a goroutine — failures are silently discarded (AGENTS.md §4.3).
func (h *Handler) notifyQuarantine(identity, reason string) {
	payload := fmt.Sprintf(`{"reason":%q,"ttl_sec":%d}`, reason, int(h.cfg.QuarantineTTLSec.Seconds()))
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, http.MethodPost,
		h.cfg.ControlURL+"/quarantine/"+identity,
		strings.NewReader(payload),
	)
	if err != nil {
		return
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Internal-Key", h.cfg.InternalKey)

	resp, err := h.ctrlClient.Do(req)
	if err != nil {
		slog.Debug("quarantine notify failed", "identity", identity, "err", err)
		return
	}
	resp.Body.Close()

	// Mark the in-memory entry as confirmed — prevents poller from releasing it
	// before the DB write was visible to the poller.
	h.quarantine.Confirm(identity)
	slog.Debug("quarantine confirmed in control-api", "identity", identity)
}

// ── Buffered ResponseWriter ───────────────────────────────────────────────────

type bufferedResponseWriter struct {
	header      http.Header
	body        bytes.Buffer
	status      int
	wroteHeader bool
}

func newBufferedResponseWriter() *bufferedResponseWriter {
	return &bufferedResponseWriter{header: make(http.Header), status: http.StatusOK}
}

func (b *bufferedResponseWriter) Header() http.Header { return b.header }
func (b *bufferedResponseWriter) WriteHeader(code int) {
	if !b.wroteHeader {
		b.status = code
		b.wroteHeader = true
	}
}
func (b *bufferedResponseWriter) Write(data []byte) (int, error) {
	if !b.wroteHeader {
		b.status = http.StatusOK
		b.wroteHeader = true
	}
	return b.body.Write(data)
}

// ── Helpers ───────────────────────────────────────────────────────────────────

func writeJSON(w http.ResponseWriter, status int, body string) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Server", "nginx")
	w.WriteHeader(status)
	_, _ = io.WriteString(w, body)
}

func stripPort(addr string) string {
	for i := len(addr) - 1; i >= 0; i-- {
		if addr[i] == ':' {
			return addr[:i]
		}
	}
	return addr
}
