// gateway/poller.go
// Background polling loops that sync gateway in-memory state with control-api.
//
// honeytokenPoller: refreshes the active token metadata every HONEYTOKEN_POLL_MS
//   (default 500 ms). Fetches full objects {token, session_id, identity, issued_at}
//   so HONEYTOKEN_REUSED events can carry correct original_session attribution.
//
// quarantinePoller: syncs operator-initiated releases every 2 s.
//   Uses epoch-aware sync: only removes CONFIRMED entries. Unconfirmed entries
//   (locally added but not yet persisted in control-api) are never removed by poll.
//   When control-api epoch advances (POST /reset), all confirmed entries are cleared.
//
// Both loops are fire-and-forget per AGENTS.md §4.3.
package main

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"time"
)

const quarantinePollInterval = 2 * time.Second

// Poller holds shared references needed by both poll loops.
type Poller struct {
	cfg        Config
	tokens     *HoneytokenStore
	quarantine *QuarantineStore
	client     *http.Client
}

func newPoller(cfg Config, tokens *HoneytokenStore, quarantine *QuarantineStore) *Poller {
	return &Poller{
		cfg:        cfg,
		tokens:     tokens,
		quarantine: quarantine,
		client: &http.Client{
			Timeout: 2 * time.Second,
		},
	}
}

// Start launches both polling goroutines.
func (p *Poller) Start(ctx context.Context) {
	go p.honeytokenPoller(ctx)
	go p.quarantinePoller(ctx)
}

// ── Honeytoken poller ─────────────────────────────────────────────────────────

func (p *Poller) honeytokenPoller(ctx context.Context) {
	interval := p.cfg.HoneytokenPollMs
	if interval <= 0 {
		interval = 100 * time.Millisecond
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			p.refreshTokens()
		}
	}
}

func (p *Poller) refreshTokens() {
	req, err := http.NewRequestWithContext(
		context.Background(),
		http.MethodGet,
		p.cfg.ControlURL+"/honeytokens",
		nil,
	)
	if err != nil {
		return
	}
	resp, err := p.client.Do(req)
	if err != nil {
		slog.Debug("honeytoken poll failed", "err", err)
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		slog.Debug("honeytoken poll non-200", "status", resp.StatusCode)
		return
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return
	}

	// New contract: GET /honeytokens returns objects {token, session_id, identity, issued_at}
	var payload struct {
		Tokens []struct {
			Token     string `json:"token"`
			SessionID string `json:"session_id"`
			Identity  string `json:"identity"`
			IssuedAt  string `json:"issued_at"`
		} `json:"tokens"`
	}
	if err := json.Unmarshal(body, &payload); err != nil {
		slog.Debug("honeytoken poll parse error", "err", err)
		return
	}
	entries := make([]HoneytokenEntry, 0, len(payload.Tokens))
	for _, t := range payload.Tokens {
		entries = append(entries, HoneytokenEntry{
			Token:     t.Token,
			SessionID: t.SessionID,
			Identity:  t.Identity,
			IssuedAt:  t.IssuedAt,
		})
	}
	p.tokens.Replace(entries)
	slog.Debug("honeytoken store refreshed", "count", len(entries))
}

// ── Quarantine poller ─────────────────────────────────────────────────────────

func (p *Poller) quarantinePoller(ctx context.Context) {
	ticker := time.NewTicker(quarantinePollInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			p.syncQuarantine()
		}
	}
}

func (p *Poller) syncQuarantine() {
	req, err := http.NewRequestWithContext(
		context.Background(),
		http.MethodGet,
		p.cfg.ControlURL+"/quarantine",
		nil,
	)
	if err != nil {
		return
	}
	resp, err := p.client.Do(req)
	if err != nil {
		slog.Debug("quarantine poll failed", "err", err)
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		slog.Debug("quarantine poll non-200", "status", resp.StatusCode)
		return
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return
	}

	// Response now includes an optional 'epoch' field for reset detection
	var payload struct {
		Epoch int64 `json:"epoch"`
		Data  []struct {
			Identity  string `json:"identity"`
			ExpiresAt string `json:"expires_at"`
		} `json:"data"`
	}
	if err := json.Unmarshal(body, &payload); err != nil {
		slog.Debug("quarantine poll parse error", "err", err)
		return
	}

	active := make(map[string]struct{}, len(payload.Data))
	for _, entry := range payload.Data {
		active[entry.Identity] = struct{}{}
	}

	// Epoch-aware sync: only removes confirmed entries that are absent from the
	// active list (operator release) or whose epoch has advanced (POST /reset).
	p.quarantine.SyncFromControlAPI(active, payload.Epoch)
}
