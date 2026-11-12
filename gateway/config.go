// gateway/config.go
// Loads all configuration from environment variables.
// NO hardcoded secrets (AGENTS.md Rule 5).
package main

import (
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	ListenAddr        string
	UpstreamURL       string
	HoneypotURL       string
	ControlURL        string
	InternalKey       string
	CanaryPaths       map[string]struct{}
	EnumThreshold     int
	EnumWindowSec     time.Duration
	TarpitDelayMs     time.Duration
	TarpitMaxConc     int
	QuarantineTTLSec  time.Duration
	Mode2Enabled      bool
	// Hardening (Tier 4)
	MaxBodyBytes    int64
	UpstreamTimeout time.Duration
	// Honeytoken polling
	HoneytokenPollMs time.Duration // configurable poll interval (default 500ms)
	// Mode 2 — MTD routing (Tier 5)
	Mode2IntervalSec int           // seconds per routing interval
	Mode2Grace       int           // ±N intervals accepted (AGENTS.md §4.5)
	Mode2Secret      string        // HMAC secret for route derivation (per-device key)
	Mode2Strict      bool          // when true, non-/m/ paths are blocked (not proxied to upstream)
	RedisURL         string        // Redis URL for nonce cache
	NonceTTLSec      int           // nonce expiry (default 180 s)
}

func loadConfig() Config {
	canaryRaw := getEnv("CANARY_PATHS", "/admin,/api/v1/ops/deploy,/.env,/backup")
	canaryPaths := make(map[string]struct{})
	for _, p := range strings.Split(canaryRaw, ",") {
		p = strings.TrimSpace(p)
		if p != "" {
			canaryPaths[p] = struct{}{}
		}
	}

	return Config{
		ListenAddr:       getEnv("LISTEN_ADDR", ":8080"),
		UpstreamURL:      getEnv("UPSTREAM_URL", "http://target-app:8001"),
		HoneypotURL:      getEnv("HONEYPOT_URL", "http://honeypot:8002"),
		ControlURL:       getEnv("CONTROL_URL", "http://control-api:8003"),
		InternalKey:      getEnv("INTERNAL_KEY", "change-me-to-a-random-32-char-string"),
		CanaryPaths:      canaryPaths,
		EnumThreshold:    getEnvInt("ENUM_THRESHOLD", 5),
		EnumWindowSec:    time.Duration(getEnvInt("ENUM_WINDOW_SEC", 10)) * time.Second,
		TarpitDelayMs:    time.Duration(getEnvInt("TARPIT_DELAY_MS", 3000)) * time.Millisecond,
		TarpitMaxConc:    getEnvInt("TARPIT_MAX_CONCURRENT", 50),
		QuarantineTTLSec: time.Duration(getEnvInt("QUARANTINE_TTL_SEC", 900)) * time.Second,
		Mode2Enabled:     getEnvBool("MODE2_ENABLED", false),
		MaxBodyBytes:     int64(getEnvInt("MAX_BODY_BYTES", 1<<20)),
		UpstreamTimeout:  time.Duration(getEnvInt("UPSTREAM_TIMEOUT_MS", 10000)) * time.Millisecond,
		HoneytokenPollMs: time.Duration(getEnvInt("HONEYTOKEN_POLL_MS", 100)) * time.Millisecond,
		// Mode 2
		Mode2IntervalSec: getEnvInt("MODE2_INTERVAL_SEC", 60),
		Mode2Grace:       getEnvInt("MODE2_GRACE", 2),
		Mode2Secret:      getEnv("MODE2_SECRET", "change-me-mode2-secret"),
		Mode2Strict:      getEnvBool("MODE2_STRICT", true),
		RedisURL:         getEnv("REDIS_URL", "redis://redis:6379/0"),
		NonceTTLSec:      getEnvInt("NONCE_TTL_SEC", 180),
	}
}

func getEnv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func getEnvInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func getEnvBool(key string, def bool) bool {
	if v := os.Getenv(key); v != "" {
		b, err := strconv.ParseBool(v)
		if err == nil {
			return b
		}
	}
	return def
}
