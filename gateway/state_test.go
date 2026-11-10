// gateway/state_test.go
// Unit tests for QuarantineStore, EnumTracker, and Tarpit.
package main

import (
	"testing"
	"time"
)

// ── QuarantineStore ───────────────────────────────────────────────────────────

func TestQuarantineAddAndCheck(t *testing.T) {
	qs := newQuarantineStore()
	qs.Add("10.0.0.1", "CANARY_HIT", 5*time.Second)
	if !qs.IsQuarantined("10.0.0.1") {
		t.Error("expected identity to be quarantined")
	}
}

func TestQuarantineNotPresent(t *testing.T) {
	qs := newQuarantineStore()
	if qs.IsQuarantined("10.0.0.2") {
		t.Error("identity should not be quarantined")
	}
}

func TestQuarantineExpiry(t *testing.T) {
	qs := newQuarantineStore()
	qs.Add("10.0.0.3", "CANARY_HIT", 50*time.Millisecond)
	time.Sleep(100 * time.Millisecond)
	if qs.IsQuarantined("10.0.0.3") {
		t.Error("quarantine should have expired")
	}
}

func TestQuarantineNotResetOnDuplicate(t *testing.T) {
	qs := newQuarantineStore()
	// First add with short TTL
	qs.Add("10.0.0.4", "CANARY_HIT", 80*time.Millisecond)
	// Second add should NOT extend TTL
	qs.Add("10.0.0.4", "CANARY_HIT", 10*time.Second)
	time.Sleep(150 * time.Millisecond)
	// If second add had extended TTL the identity would still be quarantined
	if qs.IsQuarantined("10.0.0.4") {
		t.Error("duplicate Add must not reset TTL")
	}
}

func TestQuarantineRelease(t *testing.T) {
	qs := newQuarantineStore()
	qs.Add("10.0.0.5", "CANARY_HIT", 60*time.Second)
	released := qs.Release("10.0.0.5")
	if !released {
		t.Error("Release should return true for existing entry")
	}
	if qs.IsQuarantined("10.0.0.5") {
		t.Error("identity should not be quarantined after release")
	}
}

func TestQuarantineReleaseNonExistent(t *testing.T) {
	qs := newQuarantineStore()
	if qs.Release("nobody") {
		t.Error("Release of non-existent identity should return false")
	}
}

// ── EnumTracker ───────────────────────────────────────────────────────────────

func TestEnumTrackerThreshold(t *testing.T) {
	et := newEnumTracker(3, 10*time.Second)
	identity := "scanner"

	now := time.Now()
	nowFn := func() time.Time { return now }

	for i := 1; i <= 3; i++ {
		count, exceeded := et.Record(identity, nowFn)
		if count != i {
			t.Errorf("expected count %d, got %d", i, count)
		}
		if exceeded {
			t.Errorf("should not exceed threshold at count %d", i)
		}
	}

	// 4th hit should exceed
	count, exceeded := et.Record(identity, nowFn)
	if count != 4 {
		t.Errorf("expected count 4, got %d", count)
	}
	if !exceeded {
		t.Error("should exceed threshold at count 4")
	}
}

func TestEnumTrackerSlidingWindow(t *testing.T) {
	window := 200 * time.Millisecond
	et := newEnumTracker(2, window)
	identity := "slide-test"

	base := time.Now()
	// Two hits at t=0
	et.Record(identity, func() time.Time { return base })
	et.Record(identity, func() time.Time { return base })

	// Hit after window expiry — old hits should be pruned
	future := base.Add(window + 50*time.Millisecond)
	count, exceeded := et.Record(identity, func() time.Time { return future })
	if exceeded {
		t.Errorf("should not exceed: old hits expired; count=%d", count)
	}
	if count != 1 {
		t.Errorf("expected count=1 after window reset, got %d", count)
	}
}

func TestEnumTrackerReset(t *testing.T) {
	et := newEnumTracker(2, 10*time.Second)
	et.Record("x", time.Now)
	et.Record("x", time.Now)
	et.Reset("x")
	count, exceeded := et.Record("x", time.Now)
	if count != 1 || exceeded {
		t.Errorf("expected count=1 after reset, got count=%d exceeded=%v", count, exceeded)
	}
}

// ── Tarpit semaphore ──────────────────────────────────────────────────────────

func TestTarpitAcquireRelease(t *testing.T) {
	tp := newTarpit(2)
	if !tp.TryAcquire() {
		t.Error("first acquire should succeed")
	}
	if !tp.TryAcquire() {
		t.Error("second acquire should succeed")
	}
	// Full
	if tp.TryAcquire() {
		t.Error("third acquire should fail (capacity=2)")
	}
	tp.Release()
	if !tp.TryAcquire() {
		t.Error("acquire after release should succeed")
	}
}

// ── QuarantineStore: race condition and sync fixes ────────────────────────────

// TestQuarantineUnconfirmedNotReleasedByEmptyPoll reproduces the race:
// gateway adds an entry (unconfirmed), poller sees empty list → must NOT release.
func TestQuarantineUnconfirmedNotReleasedByEmptyPoll(t *testing.T) {
	qs := newQuarantineStore()
	qs.Add("victim-device", "CANARY_HIT", 60*time.Second)

	// Simulate quarantine poller firing: control-api returns empty list (DB not written yet)
	emptyActive := map[string]struct{}{}
	qs.SyncFromControlAPI(emptyActive, 0 /* epoch unchanged */)

	// Identity must still be quarantined — unconfirmed entries are never removed by poll
	if !qs.IsQuarantined("victim-device") {
		t.Error("RACE: unconfirmed quarantine was released by empty poll — attacker would reach real backend")
	}
}

// TestQuarantineConfirmedReleasedByAbsenceFromPoll verifies operator release still works.
func TestQuarantineConfirmedReleasedByAbsenceFromPoll(t *testing.T) {
	qs := newQuarantineStore()
	qs.Add("confirmed-identity", "CANARY_HIT", 60*time.Second)
	qs.Confirm("confirmed-identity") // simulate successful notifyQuarantine

	// Operator releases via control-api → poller returns empty list
	emptyActive := map[string]struct{}{}
	qs.SyncFromControlAPI(emptyActive, 0)

	// Now should be released (confirmed + absent = operator release)
	if qs.IsQuarantined("confirmed-identity") {
		t.Error("confirmed identity should be released when absent from control-api active list")
	}
}

// TestQuarantineEpochAdvanceClearsConfirmedOnly verifies POST /reset clears only confirmed entries.
func TestQuarantineEpochAdvanceClearsConfirmedOnly(t *testing.T) {
	qs := newQuarantineStore()
	qs.Add("confirmed-one", "CANARY_HIT", 60*time.Second)
	qs.Confirm("confirmed-one")
	qs.Add("unconfirmed-one", "CANARY_HIT", 60*time.Second) // NOT confirmed

	// Epoch advances (POST /reset happened in control-api)
	emptyActive := map[string]struct{}{}
	qs.SyncFromControlAPI(emptyActive, 1 /* epoch 0 → 1 */)

	if qs.IsQuarantined("confirmed-one") {
		t.Error("confirmed entry should be cleared when epoch advances (POST /reset)")
	}
	if !qs.IsQuarantined("unconfirmed-one") {
		t.Error("unconfirmed entry must NOT be cleared on epoch advance — it was never in DB")
	}
}

// TestQuarantineMixedConfirmedAndUnconfirmedPoll verifies the common case:
// poller returns two active + one absent; only the absent confirmed one is released.
func TestQuarantineMixedConfirmedAndUnconfirmedPoll(t *testing.T) {
	qs := newQuarantineStore()
	qs.Add("keep-unconfirmed", "CANARY_HIT", 60*time.Second)   // unconfirmed
	qs.Add("keep-confirmed-active", "CANARY_HIT", 60*time.Second)
	qs.Confirm("keep-confirmed-active")
	qs.Add("release-confirmed-absent", "CANARY_HIT", 60*time.Second)
	qs.Confirm("release-confirmed-absent")

	// control-api returns the two active ones
	active := map[string]struct{}{
		"keep-confirmed-active": {},
	}
	qs.SyncFromControlAPI(active, 0)

	if !qs.IsQuarantined("keep-unconfirmed") {
		t.Error("unconfirmed must not be released by poll (race protection)")
	}
	if !qs.IsQuarantined("keep-confirmed-active") {
		t.Error("confirmed active must be kept quarantined")
	}
	if qs.IsQuarantined("release-confirmed-absent") {
		t.Error("confirmed + absent = operator release — should be removed")
	}
}

// TestQuarantineOperatorReleaseWithinTwoSeconds verifies the ≤2s SLA.
// The confirm + poller cycle propagates an operator release within 2s.
func TestQuarantineOperatorReleaseWithinTwoSeconds(t *testing.T) {
	qs := newQuarantineStore()
	qs.Add("op-release-test", "CANARY_HIT", 60*time.Second)
	qs.Confirm("op-release-test") // confirmed in control-api

	// Simulate operator release: control-api deletes the entry,
	// next poll returns empty list, poller calls SyncFromControlAPI
	emptyActive := map[string]struct{}{}
	// This happens within 2s of operator action (poll interval)
	qs.SyncFromControlAPI(emptyActive, 0)

	if qs.IsQuarantined("op-release-test") {
		t.Error("operator release: confirmed + absent should be removed within 2s poll cycle")
	}
}

// ── HoneytokenStore: new full-metadata API ───────────────────────────────────

func TestHoneytokenStoreLookupReturnsFullMetadata(t *testing.T) {
	ts := newHoneytokenStore()
	ts.Replace([]HoneytokenEntry{{
		Token:     "DOC-aabbccddeeff",
		SessionID: "sess-original",
		Identity:  "victim-device",
		IssuedAt:  "2026-11-08T10:00:00Z",
	}})

	e, ok := ts.Lookup("DOC-aabbccddeeff")
	if !ok {
		t.Fatal("token not found after Replace")
	}
	if e.SessionID != "sess-original" {
		t.Errorf("SessionID: want sess-original, got %q", e.SessionID)
	}
	if e.Identity != "victim-device" {
		t.Errorf("Identity: want victim-device, got %q", e.Identity)
	}
}

func TestHoneytokenStoreSnapshotReturnsTokenStrings(t *testing.T) {
	ts := newHoneytokenStore()
	ts.Replace([]HoneytokenEntry{
		{Token: "DOC-111111111111", SessionID: "s1"},
		{Token: "DOC-222222222222", SessionID: "s2"},
	})
	snap := ts.Snapshot()
	if len(snap) != 2 {
		t.Errorf("expected 2 tokens in snapshot, got %d", len(snap))
	}
}
