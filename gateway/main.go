// gateway/main.go
// TCAD Mesh — Gateway service entry point.
// Wires config, handler, hardening middleware, polling loops, and HTTP server.
package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

const version = "0.1.0"

var startTime = time.Now()

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))
	slog.SetDefault(logger)

	cfg := loadConfig()
	h := newHandler(cfg)

	// ── Start background polling loops ────────────────────────────────────────
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	poller := newPoller(cfg, h.tokens, h.quarantine)
	poller.Start(ctx)

	// ── Emit SYSTEM_START ─────────────────────────────────────────────────────
	h.dispatcher.Emit(newEvent(
		"SYSTEM_START", "info",
		"127.0.0.1", "gateway", "system", "INTERNAL", "/", "",
		0, map[string]any{"version": version, "mode2_enabled": cfg.Mode2Enabled},
	))

	// ── Middleware stack ──────────────────────────────────────────────────────
	// Order: recovery → body limit → detection pipeline
	var handler http.Handler = h
	handler = limitBodyMiddleware(cfg.MaxBodyBytes, handler)
	handler = recoveryMiddleware(handler)

	mux := http.NewServeMux()
	mux.HandleFunc("/health", healthHandler)
	mux.Handle("/", handler)

	// ── HTTP Server with hardened timeouts ────────────────────────────────────
	srv := &http.Server{
		Addr:    cfg.ListenAddr,
		Handler: mux,
		// ReadHeaderTimeout: guards slow-loris header attacks
		ReadHeaderTimeout: 5 * time.Second,
		// ReadTimeout: max time to read full request including body
		ReadTimeout: 15 * time.Second,
		// WriteTimeout: must exceed TarpitDelayMs (3 s default) + upstream timeout
		WriteTimeout: time.Duration(cfg.TarpitDelayMs) + cfg.UpstreamTimeout + 10*time.Second,
		// IdleTimeout: keep-alive connection limit
		IdleTimeout: 90 * time.Second,
		// MaxHeaderBytes: reject oversized headers (16 KB)
		MaxHeaderBytes: 16 << 10,
	}

	// ── Graceful shutdown ─────────────────────────────────────────────────────
	idleConnsClosed := make(chan struct{})
	go func() {
		sigCh := make(chan os.Signal, 1)
		signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
		<-sigCh
		slog.Info("shutting down gateway gracefully")
		cancel() // stop pollers
		shutCtx, shutCancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer shutCancel()
		if err := srv.Shutdown(shutCtx); err != nil {
			slog.Error("shutdown error", "err", err)
		}
		close(idleConnsClosed)
	}()

	slog.Info("gateway listening",
		"addr", cfg.ListenAddr,
		"version", version,
		"max_body_bytes", cfg.MaxBodyBytes,
		"upstream_timeout_ms", cfg.UpstreamTimeout.Milliseconds(),
	)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		slog.Error("server error", "err", err)
		os.Exit(1)
	}
	<-idleConnsClosed
	slog.Info("gateway shutdown complete")
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Server", "nginx")
	w.WriteHeader(http.StatusOK)
	uptime := time.Since(startTime).Round(time.Second).String()
	_, _ = w.Write([]byte(`{"status":"ok","service":"gateway","version":"` + version + `","uptime":"` + uptime + `"}`))
}
