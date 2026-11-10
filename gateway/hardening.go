// gateway/hardening.go
// Tier 4 hardening middleware.
//
// Implements:
//   - Request body size limit (MAX_BODY_BYTES, default 1 MB)
//   - Panic recovery so a single bad request never crashes the server
//
// Per-request timeout is handled by:
//   - http.Server.WriteTimeout  (covers tarpit + upstream)
//   - http.Server.ReadHeaderTimeout (slow-loris guard)
//   - http.Transport.ResponseHeaderTimeout (upstream stall guard)
package main

import (
	"io"
	"log/slog"
	"net/http"
	"runtime/debug"
)

// limitBodyMiddleware rejects requests whose Content-Length exceeds maxBytes
// with 413 Request Entity Too Large, and caps body readers for chunked bodies.
func limitBodyMiddleware(maxBytes int64, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if maxBytes > 0 && r.ContentLength > maxBytes {
			writeJSON(w, http.StatusRequestEntityTooLarge,
				`{"error":"request body too large","code":413}`)
			return
		}
		if maxBytes > 0 && r.Body != nil {
			r.Body = http.MaxBytesReader(w, r.Body, maxBytes)
		}
		next.ServeHTTP(w, r)
	})
}

// recoveryMiddleware catches panics in handlers and returns 500.
// Prevents goroutine leaks from panics — the server keeps running.
func recoveryMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if rec := recover(); rec != nil {
				stack := debug.Stack()
				if len(stack) > 1024 {
					stack = stack[:1024]
				}
				slog.Error("panic recovered in handler",
					"panic", rec,
					"stack", string(stack),
				)
				writeJSON(w, http.StatusInternalServerError,
					`{"error":"internal server error","code":500}`)
			}
		}()
		next.ServeHTTP(w, r)
	})
}

// drainAndClose discards remaining body bytes then closes.
// Prevents connection reuse issues when large bodies are rejected early.
func drainAndClose(body io.ReadCloser) {
	if body == nil {
		return
	}
	_, _ = io.Copy(io.Discard, io.LimitReader(body, 1<<16))
	_ = body.Close()
}
