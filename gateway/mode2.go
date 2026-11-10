// gateway/mode2.go
// Mode 2 — Time-based Moving-Target Defense (MTD) routing.
//
// Spec (AGENTS.md §4.5):
//   Route format:   /m/<interval>-<mac16>/<canonical_path>
//   MAC calc:       HMAC-SHA256(MODE2_SECRET, "route:" + interval_str), first 16 hex chars
//   Interval:       floor(unix_time / INTERVAL_SEC)  — calculated ONCE per request
//   Grace window:   interval ∈ [cur-GRACE, cur+GRACE] AND mac correct → accept
//   Tripwire:       interval older than grace window BUT mac is correct → TRIPWIRE_HIT → quarantine → honeypot
//   Anti-replay:    X-Device-ID + X-Timestamp + X-Nonce + X-Signature required
//                   X-Signature = HMAC(MODE2_SECRET, method|path|sha256(body)|timestamp|nonce)
//                   Nonce stored in Redis: SET NX EX 180; duplicate → REPLAY_REJECTED
//   Constant-time:  ALL mac/signature comparisons use crypto/subtle.ConstantTimeCompare
//
// When MODE2_ENABLED=false, none of this code runs (zero Mode 1 regression risk).
package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"
)

const (
	mode2Prefix    = "/m/"
	mac16Len       = 16
	sigHeaderName  = "X-Signature"
	nonceHeader    = "X-Nonce"
	tsHeader       = "X-Timestamp"
	deviceIDHeader = "X-Device-ID"
)

// Mode2Request holds the parsed components of a Mode 2 URL.
type Mode2Request struct {
	Interval      int64  // parsed interval from URL
	MAC16         string // 16-hex mac from URL (lower-case)
	CanonicalPath string // the real path after stripping the prefix
}

// ParseMode2Path parses a URL path of the form /m/<interval>-<mac16>/<rest>.
// Returns (parsed, true) on success, (zero, false) if the path is not Mode 2 format.
func ParseMode2Path(path string) (Mode2Request, bool) {
	if !strings.HasPrefix(path, mode2Prefix) {
		return Mode2Request{}, false
	}
	// strip "/m/"
	rest := path[len(mode2Prefix):]
	// find the slash after the routing segment
	slashIdx := strings.Index(rest, "/")
	var routeSeg, canonPath string
	if slashIdx == -1 {
		routeSeg = rest
		canonPath = "/"
	} else {
		routeSeg = rest[:slashIdx]
		canonPath = rest[slashIdx:]
	}
	// routeSeg must be "<interval>-<mac16>"
	dashIdx := strings.LastIndex(routeSeg, "-")
	if dashIdx < 1 {
		return Mode2Request{}, false
	}
	intervalStr := routeSeg[:dashIdx]
	mac16 := routeSeg[dashIdx+1:]
	if len(mac16) != mac16Len {
		return Mode2Request{}, false
	}
	var interval int64
	_, err := fmt.Sscanf(intervalStr, "%d", &interval)
	if err != nil || interval < 0 {
		return Mode2Request{}, false
	}
	return Mode2Request{
		Interval:      interval,
		MAC16:         strings.ToLower(mac16),
		CanonicalPath: canonPath,
	}, true
}

// DeriveMAC16 computes HMAC-SHA256(secret, "route:"+intervalStr) and
// returns the first 16 hex characters (lower-case).
// This is O(1) — one HMAC call, no loops.
func DeriveMAC16(secret string, interval int64) string {
	msg := fmt.Sprintf("route:%d", interval)
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(msg))
	return hex.EncodeToString(mac.Sum(nil))[:mac16Len]
}

// CurrentInterval returns floor(unix_time / intervalSec).
// Called ONCE per request to prevent time-oracle attacks (AGENTS.md §5).
func CurrentInterval(now time.Time, intervalSec int) int64 {
	return now.Unix() / int64(intervalSec)
}

// ValidateMAC16 performs a constant-time comparison of two 16-char hex strings.
// Returns (valid, withinGrace) where:
//   - valid=true means the MAC is cryptographically correct
//   - withinGrace=true means the interval is within [cur-grace, cur+grace]
//
// AGENTS.md §4.5: "Always use crypto/subtle.ConstantTimeCompare"
func ValidateMAC16(secret string, submitted Mode2Request, curInterval int64, grace int) (valid, withinGrace bool) {
	// Compute expected MAC for the submitted interval
	expected := DeriveMAC16(secret, submitted.Interval)

	// Constant-time compare — prevents timing side-channel leaks
	macMatch := subtle.ConstantTimeCompare(
		[]byte(submitted.MAC16),
		[]byte(expected),
	) == 1

	if !macMatch {
		return false, false
	}

	// MAC is valid — check if interval is within grace window
	diff := submitted.Interval - curInterval
	if diff < 0 {
		diff = -diff
	}
	inGrace := diff <= int64(grace)
	return true, inGrace
}

// BodySHA256 computes SHA-256 of the request body and returns lower-hex.
// The body is re-set on the request after reading.
func BodySHA256(r *http.Request) (string, error) {
	if r.Body == nil || r.ContentLength == 0 {
		return hex.EncodeToString(sha256.New().Sum(nil)), nil
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	if err != nil {
		return "", err
	}
	r.Body = io.NopCloser(strings.NewReader(string(body)))
	h := sha256.Sum256(body)
	return hex.EncodeToString(h[:]), nil
}

// ComputeSignature computes the anti-replay request signature:
//   HMAC-SHA256(MODE2_SECRET, method | path | sha256(body) | timestamp | nonce)
func ComputeSignature(secret, method, path, bodySHA256, timestamp, nonce string) string {
	msg := method + "|" + path + "|" + bodySHA256 + "|" + timestamp + "|" + nonce
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(msg))
	return hex.EncodeToString(mac.Sum(nil))
}

// VerifySignature performs a constant-time verification of the request signature.
func VerifySignature(secret, method, path, bodySHA256, timestamp, nonce, submitted string) bool {
	expected := ComputeSignature(secret, method, path, bodySHA256, timestamp, nonce)
	return subtle.ConstantTimeCompare(
		[]byte(strings.ToLower(submitted)),
		[]byte(expected),
	) == 1
}

// handleMode2 is called by the Handler when MODE2_ENABLED=true and the path
// starts with /m/.  It returns true if it handled the request (caller must return).
// It returns false if the path is not Mode 2 format (fall through to Mode 1 pipeline).
func (h *Handler) handleMode2(w http.ResponseWriter, r *http.Request,
	identity, sessionID, srcIP, safeUA string, now time.Time) bool {

	parsed, ok := ParseMode2Path(r.URL.Path)
	if !ok {
		// Not a /m/ path — fall through to Mode 1
		return false
	}

	curInterval := CurrentInterval(now, h.cfg.Mode2IntervalSec)
	safePath := sanitizePath(parsed.CanonicalPath)
	method := r.Method

	// ── Step 1: Validate MAC (O(1), constant-time) ────────────────────────────
	valid, withinGrace := ValidateMAC16(h.cfg.Mode2Secret, parsed, curInterval, h.cfg.Mode2Grace)

	if !valid {
		// Bad MAC — treat as unknown path → 404 (same as Mode 1)
		slog.Debug("mode2 invalid MAC", "identity", identity, "path", safePath)
		writeJSON(w, http.StatusNotFound, `{"error":"not found","code":404}`)
		return true
	}

	if !withinGrace {
		// Valid MAC but stale interval → TRIPWIRE_HIT
		slog.Info("TRIPWIRE_HIT", "identity", identity, "interval", parsed.Interval, "cur", curInterval)
		h.quarantine.Add(identity, "TRIPWIRE_HIT", h.cfg.QuarantineTTLSec)
		h.dispatcher.Emit(newEvent("TRIPWIRE_HIT", "high",
			srcIP, identity, sessionID, method, safePath, safeUA,
			200, map[string]any{
				"submitted_interval": parsed.Interval,
				"current_interval":   curInterval,
				"grace":              h.cfg.Mode2Grace,
			},
		))
		h.dispatcher.Emit(newEvent("QUARANTINED", "high",
			srcIP, identity, sessionID, method, safePath, safeUA,
			200, map[string]any{"reason": "TRIPWIRE_HIT", "ttl_sec": h.cfg.QuarantineTTLSec.Seconds()},
		))
		go h.notifyQuarantine(identity, "TRIPWIRE_HIT")
		// Rewrite request path to canonical before proxying to honeypot
		r2 := r.Clone(r.Context())
		r2.URL.Path = parsed.CanonicalPath
		h.honeypot.ServeHTTP(w, r2)
		return true
	}

	// ── Step 2: Anti-replay (AGENTS.md §4.5) ─────────────────────────────────
	deviceID := r.Header.Get(deviceIDHeader)
	timestamp := r.Header.Get(tsHeader)
	nonce := r.Header.Get(nonceHeader)
	sig := r.Header.Get(sigHeaderName)

	if deviceID == "" || timestamp == "" || nonce == "" || sig == "" {
		slog.Info("mode2 missing anti-replay headers", "identity", identity)
		writeJSON(w, http.StatusBadRequest, `{"error":"missing mode2 headers","code":400}`)
		return true
	}

	// Compute body hash for signature verification
	bodySHA, err := BodySHA256(r)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, `{"error":"unreadable body","code":400}`)
		return true
	}

	// Verify signature (constant-time)
	if !VerifySignature(h.cfg.Mode2Secret, method, parsed.CanonicalPath,
		bodySHA, timestamp, nonce, sig) {
		slog.Info("mode2 signature mismatch", "identity", identity)
		writeJSON(w, http.StatusUnauthorized, `{"error":"invalid signature","code":401}`)
		return true
	}

	// Check nonce uniqueness in Redis
	nonceKey := fmt.Sprintf("nonce:%s:%s", deviceID, nonce)
	stored, err := h.nonceStore.SetNX(r.Context(), nonceKey, h.cfg.NonceTTLSec)
	if err != nil {
		// Redis down — fail open with a warning (availability > strict replay prevention)
		slog.Warn("nonce store unavailable, skipping replay check", "err", err)
	} else if !stored {
		// Nonce already seen → replay attack
		slog.Info("REPLAY_REJECTED", "identity", identity, "nonce", nonce)
		h.dispatcher.Emit(newEvent("REPLAY_REJECTED", "high",
			srcIP, identity, sessionID, method, safePath, safeUA,
			401, map[string]any{"nonce": sanitizeIdentity(nonce)},
		))
		writeJSON(w, http.StatusUnauthorized, `{"error":"replay rejected","code":401}`)
		return true
	}

	// ── Step 3: Valid Mode 2 request — proxy to target-app ───────────────────
	slog.Debug("mode2 valid request", "identity", identity, "path", parsed.CanonicalPath)
	r2 := r.Clone(r.Context())
	r2.URL.Path = parsed.CanonicalPath
	// Strip Mode 2 headers before forwarding (don't leak internal protocol to upstream)
	r2.Header.Del(sigHeaderName)
	r2.Header.Del(nonceHeader)
	r2.Header.Del(tsHeader)

	buf := newBufferedResponseWriter()
	h.upstream.ServeHTTP(buf, r2)

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
	_, _ = io.Copy(w, strings.NewReader(buf.body.String()))
	return true
}
