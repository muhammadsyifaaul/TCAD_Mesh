// gateway/nonce.go
// Anti-replay nonce store.
//
// Primary:  Redis  — SET NX EX <ttl>  (atomic, clustered)
// Fallback: in-memory map with TTL reaping — used when Redis is unreachable
//           or when MODE2_ENABLED=false (nonce store is still created but never called).
//
// The fallback is intentionally simple: it keeps the gateway available even
// if Redis is down, at the cost of replay protection being degraded to single-
// instance memory (still effective for the demo environment).
package main

import (
	"bufio"
	"context"
	"fmt"
	"log/slog"
	"net"
	"strings"
	"sync"
	"time"
)

// NonceStore is the interface both Redis and in-memory stores implement.
type NonceStore interface {
	// SetNX stores key with ttlSec expiry if it doesn't exist.
	// Returns (true, nil) if stored (nonce is fresh).
	// Returns (false, nil) if key already exists (replay detected).
	// Returns (false, err) on store failure.
	SetNX(ctx context.Context, key string, ttlSec int) (bool, error)
}

// ── Redis store ───────────────────────────────────────────────────────────────

// redisStore talks to Redis using the raw RESP protocol over a single TCP
// connection. We intentionally avoid importing a Redis client library
// (AGENTS.md: minimal dependencies) — RESP is simple enough for SET NX EX.
type redisStore struct {
	addr string // host:port
}

func newRedisStore(redisURL string) *redisStore {
	// Parse redis://host:port/db → host:port
	addr := "redis:6379" // default
	url := strings.TrimPrefix(redisURL, "redis://")
	if idx := strings.Index(url, "/"); idx != -1 {
		url = url[:idx]
	}
	if url != "" {
		addr = url
	}
	return &redisStore{addr: addr}
}

func (r *redisStore) SetNX(ctx context.Context, key string, ttlSec int) (bool, error) {
	d := net.Dialer{}
	conn, err := d.DialContext(ctx, "tcp", r.addr)
	if err != nil {
		return false, fmt.Errorf("redis connect: %w", err)
	}
	defer conn.Close()

	// SET key "" NX EX ttlSec — 6 RESP bulk strings (SET, key, value, NX, EX, ttl)
	cmd := fmt.Sprintf("*6\r\n$3\r\nSET\r\n$%d\r\n%s\r\n$0\r\n\r\n$2\r\nNX\r\n$2\r\nEX\r\n$%d\r\n%d\r\n",
		len(key), key, len(fmt.Sprintf("%d", ttlSec)), ttlSec)

	deadline := time.Now().Add(2 * time.Second)
	_ = conn.SetDeadline(deadline)

	if _, err = conn.Write([]byte(cmd)); err != nil {
		return false, fmt.Errorf("redis write: %w", err)
	}

	// Read response: +OK (stored) or $-1 / *0 (already exists)
	reader := bufio.NewReader(conn)
	line, err := reader.ReadString('\n')
	if err != nil {
		return false, fmt.Errorf("redis read: %w", err)
	}
	line = strings.TrimSpace(line)

	switch {
	case line == "+OK":
		return true, nil
	case line == "$-1", line == "*0", line == "+(nil)":
		return false, nil
	case strings.HasPrefix(line, "_"):
		// RESP3 null bulk: _\r\n
		return false, nil
	default:
		// Any other response (including errors) — treat as "already set" (conservative)
		slog.Debug("redis unexpected response", "resp", line)
		return false, nil
	}
}

// ── In-memory fallback store ──────────────────────────────────────────────────

type memNonceEntry struct {
	expiresAt time.Time
}

type memNonceStore struct {
	mu      sync.Mutex
	entries map[string]memNonceEntry
}

func newMemNonceStore() *memNonceStore {
	s := &memNonceStore{entries: make(map[string]memNonceEntry)}
	go s.reap()
	return s
}

func (s *memNonceStore) SetNX(_ context.Context, key string, ttlSec int) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := time.Now()
	if e, ok := s.entries[key]; ok && now.Before(e.expiresAt) {
		return false, nil // already exists and not expired
	}
	s.entries[key] = memNonceEntry{expiresAt: now.Add(time.Duration(ttlSec) * time.Second)}
	return true, nil
}

func (s *memNonceStore) reap() {
	ticker := time.NewTicker(60 * time.Second)
	defer ticker.Stop()
	for range ticker.C {
		now := time.Now()
		s.mu.Lock()
		for k, e := range s.entries {
			if now.After(e.expiresAt) {
				delete(s.entries, k)
			}
		}
		s.mu.Unlock()
	}
}

// ── Factory ───────────────────────────────────────────────────────────────────

// newNonceStore probes Redis; falls back to in-memory if unreachable.
func newNonceStore(redisURL string, mode2Enabled bool) NonceStore {
	if !mode2Enabled {
		// Mode 2 disabled — return a no-op store (never called anyway)
		return newMemNonceStore()
	}
	rs := newRedisStore(redisURL)
	// Probe Redis with a short timeout
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_, err := rs.SetNX(ctx, "tcad:probe", 1)
	if err != nil {
		slog.Warn("Redis unreachable, using in-memory nonce store", "err", err)
		return newMemNonceStore()
	}
	slog.Info("Redis nonce store connected", "addr", rs.addr)
	return rs
}
