// gateway/state.go
// In-memory state stores: quarantine registry and sliding-window 404 counter.
// All operations are safe for concurrent use.
package main

import (
	"log/slog"
	"sync"
	"time"
)

// ── Quarantine store ──────────────────────────────────────────────────────────
//
// Design (fixes the quarantine-sync race documented in bench_ttd_ttc.json):
//
//   Problem: gateway adds an identity to in-memory quarantine, then async-notifies
//   control-api (notifyQuarantine goroutine). The quarantine poller fires in the
//   window between in-memory add and DB write completion, sees an empty list from
//   control-api, and removes the entry — sending an attacker back to the real backend.
//
//   Fix: quarantineEntry has a 'confirmed' flag. An entry is 'unconfirmed' from the
//   moment it is created locally until notifyQuarantine succeeds (confirmed=true).
//   SyncFromControlAPI ONLY removes entries that are:
//     (a) confirmed AND absent from the API response, OR
//     (b) expired (TTL exceeded).
//   Unconfirmed entries are kept quarantined unconditionally until:
//     (a) confirmation arrives (notifyQuarantine sets confirmed=true), OR
//     (b) a confirmation timeout (confirmTTL) expires and the entry TTL has passed.
//
//   Operator releases: remain effective within ≤2s. When control-api returns a
//   release (confirmed entry absent from the active list), it is removed.
//
//   POST /reset behaviour: control-api increments a monotonic epoch and returns it
//   in GET /quarantine. When the gateway observes a new epoch it clears all
//   CONFIRMED entries (unconfirmed ones stay until confirmed or TTL expires).
//   This is deterministic: the gateway never infers reset from "list is empty" alone.

type quarantineEntry struct {
	ExpiresAt    time.Time
	Reason       string
	Confirmed    bool      // true once POST /quarantine/{id} succeeded in control-api
	CreatedAt    time.Time // used to compute confirmation timeout
}

const confirmTTL = 10 * time.Second // max time to wait for DB confirmation

// QuarantineStore holds the set of quarantined identities with TTL expiry.
type QuarantineStore struct {
	mu       sync.RWMutex
	entries  map[string]quarantineEntry
	epoch    int64 // last known control-api epoch
}

func newQuarantineStore() *QuarantineStore {
	qs := &QuarantineStore{entries: make(map[string]quarantineEntry)}
	go qs.reap()
	return qs
}

// Add quarantines an identity as UNCONFIRMED.
// If already quarantined (confirmed or not), TTL is NOT reset.
func (qs *QuarantineStore) Add(identity, reason string, ttl time.Duration) {
	qs.mu.Lock()
	defer qs.mu.Unlock()
	if _, exists := qs.entries[identity]; exists {
		return
	}
	qs.entries[identity] = quarantineEntry{
		ExpiresAt: time.Now().Add(ttl),
		Reason:    reason,
		Confirmed: false,
		CreatedAt: time.Now(),
	}
}

// Confirm marks an entry as confirmed (called after successful POST to control-api).
func (qs *QuarantineStore) Confirm(identity string) {
	qs.mu.Lock()
	defer qs.mu.Unlock()
	if e, ok := qs.entries[identity]; ok {
		e.Confirmed = true
		qs.entries[identity] = e
	}
}

// IsQuarantined returns true if the identity is currently quarantined
// (regardless of confirmed state — unconfirmed entries are still enforced).
func (qs *QuarantineStore) IsQuarantined(identity string) bool {
	qs.mu.RLock()
	defer qs.mu.RUnlock()
	e, ok := qs.entries[identity]
	return ok && time.Now().Before(e.ExpiresAt)
}

// Release removes a quarantine entry (operator action).
func (qs *QuarantineStore) Release(identity string) bool {
	qs.mu.Lock()
	defer qs.mu.Unlock()
	_, existed := qs.entries[identity]
	delete(qs.entries, identity)
	return existed
}

// reap periodically removes expired and timed-out-unconfirmed entries.
func (qs *QuarantineStore) reap() {
	ticker := time.NewTicker(60 * time.Second)
	defer ticker.Stop()
	for range ticker.C {
		now := time.Now()
		qs.mu.Lock()
		for id, e := range qs.entries {
			expired := now.After(e.ExpiresAt)
			// Unconfirmed entries that exceed confirmTTL AND their normal TTL are removed.
			// (If TTL is still valid but confirmation timed out, keep them quarantined
			// until natural expiry — prefer false negatives over false positives.)
			if expired {
				delete(qs.entries, id)
			}
		}
		qs.mu.Unlock()
	}
}

// SyncFromControlAPI is the safe quarantine sync:
//   - NEVER removes unconfirmed entries (they haven't been persisted yet).
//   - Removes a CONFIRMED entry only if it is absent from the active API list
//     (operator release) AND the current epoch matches.
//   - Clears all CONFIRMED entries when the epoch advances (POST /reset).
func (qs *QuarantineStore) SyncFromControlAPI(activeFromAPI map[string]struct{}, newEpoch int64) {
	qs.mu.Lock()
	defer qs.mu.Unlock()

	epochAdvanced := newEpoch > qs.epoch
	if epochAdvanced {
		slog.Info("quarantine epoch advanced — clearing confirmed entries",
			"old_epoch", qs.epoch, "new_epoch", newEpoch)
		qs.epoch = newEpoch
	}

	for id, e := range qs.entries {
		if !e.Confirmed {
			// Never remove unconfirmed entries via poll — they will be confirmed
			// or expire naturally. Protects against the race.
			continue
		}
		if epochAdvanced {
			// Epoch bump (POST /reset) clears all confirmed entries deterministically.
			delete(qs.entries, id)
			slog.Debug("quarantine cleared on epoch advance", "identity", id)
			continue
		}
		if _, stillActive := activeFromAPI[id]; !stillActive {
			// Confirmed + absent from API = operator release applied.
			delete(qs.entries, id)
			slog.Info("quarantine released via operator (control-api sync)", "identity", id)
		}
	}
}

// ── Sliding-window 404 counter ────────────────────────────────────────────────

type hit struct{ at time.Time }

type EnumTracker struct {
	mu        sync.Mutex
	hits      map[string][]hit
	threshold int
	window    time.Duration
}

func newEnumTracker(threshold int, window time.Duration) *EnumTracker {
	et := &EnumTracker{
		hits:      make(map[string][]hit),
		threshold: threshold,
		window:    window,
	}
	go et.reap()
	return et
}

func (et *EnumTracker) Record(identity string, nowFn func() time.Time) (int, bool) {
	now := nowFn()
	cutoff := now.Add(-et.window)
	et.mu.Lock()
	defer et.mu.Unlock()
	fresh := et.hits[identity][:0]
	for _, h := range et.hits[identity] {
		if h.at.After(cutoff) {
			fresh = append(fresh, h)
		}
	}
	fresh = append(fresh, hit{at: now})
	et.hits[identity] = fresh
	count := len(fresh)
	return count, count > et.threshold
}

func (et *EnumTracker) Reset(identity string) {
	et.mu.Lock()
	defer et.mu.Unlock()
	delete(et.hits, identity)
}

func (et *EnumTracker) reap() {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()
	for range ticker.C {
		cutoff := time.Now().Add(-et.window)
		et.mu.Lock()
		for id, hs := range et.hits {
			fresh := hs[:0]
			for _, h := range hs {
				if h.at.After(cutoff) {
					fresh = append(fresh, h)
				}
			}
			if len(fresh) == 0 {
				delete(et.hits, id)
			} else {
				et.hits[id] = fresh
			}
		}
		et.mu.Unlock()
	}
}

// ── Tarpit semaphore ──────────────────────────────────────────────────────────

type Tarpit struct{ sem chan struct{} }

func newTarpit(maxConcurrent int) *Tarpit {
	return &Tarpit{sem: make(chan struct{}, maxConcurrent)}
}

func (t *Tarpit) TryAcquire() bool {
	select {
	case t.sem <- struct{}{}:
		return true
	default:
		return false
	}
}

func (t *Tarpit) Release() { <-t.sem }

// ── HoneytokenStore ───────────────────────────────────────────────────────────
// Stores full honeytoken metadata so the gateway can attribute HONEYTOKEN_REUSED
// events to the correct issuing session (fixes 0/30 session match bug).

// HoneytokenEntry holds the full metadata for an issued honeytoken.
type HoneytokenEntry struct {
	Token     string
	SessionID string // session that RECEIVED the token (issuing session)
	Identity  string // identity that received the token
	IssuedAt  string
}

type HoneytokenStore struct {
	mu     sync.RWMutex
	tokens map[string]HoneytokenEntry // token → full metadata
}

func newHoneytokenStore() *HoneytokenStore {
	return &HoneytokenStore{tokens: make(map[string]HoneytokenEntry)}
}

// Replace atomically swaps the full token map.
func (h *HoneytokenStore) Replace(entries []HoneytokenEntry) {
	next := make(map[string]HoneytokenEntry, len(entries))
	for _, e := range entries {
		next[e.Token] = e
	}
	h.mu.Lock()
	h.tokens = next
	h.mu.Unlock()
}

// Lookup returns the entry for a given token, or (zero, false) if not found.
func (h *HoneytokenStore) Lookup(token string) (HoneytokenEntry, bool) {
	h.mu.RLock()
	e, ok := h.tokens[token]
	h.mu.RUnlock()
	return e, ok
}

// Snapshot returns a copy of all token strings (for scanning the request URI).
func (h *HoneytokenStore) Snapshot() []string {
	h.mu.RLock()
	defer h.mu.RUnlock()
	out := make([]string, 0, len(h.tokens))
	for t := range h.tokens {
		out = append(out, t)
	}
	return out
}
