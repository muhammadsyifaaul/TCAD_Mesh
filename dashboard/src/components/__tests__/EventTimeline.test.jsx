/**
 * dashboard/src/components/__tests__/EventTimeline.test.jsx
 *
 * Render tests for EventTimeline using vitest + @testing-library/react + jsdom.
 * Mock strategy: mock ../../../hooks so useEvents() returns controlled data.
 *
 * Key behaviours tested:
 *   1. Normal events   — CANARY_HIT row visible, correct event type badge shown
 *   2. ISSUED collapse — 3 HONEYTOKEN_ISSUED events by the same identity
 *                        in the same minute are collapsed to 1 aggregated row
 *                        ("3 token diterbitkan → …") when ISSUED filter is toggled on
 *   3. ISSUED hidden   — by default HONEYTOKEN_ISSUED rows are NOT shown
 *   4. Empty state     — "Belum ada event" shown
 *   5. Loading state   — "Memuat event…" shown
 *   6. Error state     — "Event tidak tersedia: …" shown
 *   7. Malformed data  — ErrorBoundary catches; only the panel is unavailable
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import { ErrorBoundary } from '../ErrorBoundary';

vi.mock('../../hooks', () => ({
  useEvents: vi.fn(),
}));

import { EventTimeline } from '../EventTimeline';
import { useEvents } from '../../hooks';

// ── Fixtures ─────────────────────────────────────────────────────────────────

function makeEvent(overrides) {
  return {
    id:         'evt-' + Math.random().toString(36).slice(2),
    ts:         '2026-11-07T10:03:00Z',
    event_type: 'CANARY_HIT',
    severity:   'high',
    mode:       1,
    src_ip:     '172.20.0.5',
    identity:   'attacker-01',
    session_id: 'sess-abc',
    method:     'GET',
    path:       '/admin',
    user_agent: 'scanner/1.0',
    status:     200,
    detail:     {},
    ...overrides,
  };
}

// Three HONEYTOKEN_ISSUED events from the same identity within the same minute
const ISSUED_EVENTS = [
  makeEvent({ id: 'ht1', event_type: 'HONEYTOKEN_ISSUED', severity: 'info', path: '/api/v1/shipments',   ts: '2026-11-07T10:03:01Z', identity: 'attacker-ht' }),
  makeEvent({ id: 'ht2', event_type: 'HONEYTOKEN_ISSUED', severity: 'info', path: '/api/v1/manifests',   ts: '2026-11-07T10:03:15Z', identity: 'attacker-ht' }),
  makeEvent({ id: 'ht3', event_type: 'HONEYTOKEN_ISSUED', severity: 'info', path: '/api/v1/routes',      ts: '2026-11-07T10:03:45Z', identity: 'attacker-ht' }),
];

const MIXED_EVENTS = [
  makeEvent({ id: 'c1', event_type: 'CANARY_HIT',    severity: 'high', path: '/admin',           identity: 'attacker-01', ts: '2026-11-07T10:04:00Z' }),
  makeEvent({ id: 'e1', event_type: 'ENUM_DETECTED', severity: 'warn', path: '/nonexistent-001', identity: 'attacker-02', ts: '2026-11-07T10:03:00Z' }),
  ...ISSUED_EVENTS,
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function mockOk(events) {
  useEvents.mockReturnValue({ data: { data: events, total: events.length }, loading: false, error: null });
}

function suppressConsoleError() {
  const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
  return () => spy.mockRestore();
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('EventTimeline', () => {
  beforeEach(() => vi.clearAllMocks());

  // ── 1. Normal events ─────────────────────────────────────────────────────
  it('renders event type badges for visible event types', () => {
    mockOk(MIXED_EVENTS);
    render(<EventTimeline />);

    // CANARY_HIT and ENUM_DETECTED both visible by default
    expect(screen.getByText('CANARY_HIT')).toBeInTheDocument();
    expect(screen.getByText('ENUM_DETECTED')).toBeInTheDocument();
  });

  // ── 2. ISSUED events collapsed when filter toggled on ────────────────────
  it('collapses 3 HONEYTOKEN_ISSUED events into one row when ISSUED filter is turned on', () => {
    mockOk(MIXED_EVENTS);
    render(<EventTimeline />);

    // Toggle ISSUED filter chip on (it's off by default)
    const issuedBtn = screen.getByText('ISSUED ⤵');
    fireEvent.click(issuedBtn);

    // Should show aggregated label "3 token diterbitkan → attacker-ht"
    expect(screen.getByText(/3 token diterbitkan/)).toBeInTheDocument();
    // The ×3 count badge
    expect(screen.getByText('×3')).toBeInTheDocument();
  });

  // ── 3. ISSUED events hidden by default ───────────────────────────────────
  it('hides HONEYTOKEN_ISSUED rows by default', () => {
    mockOk(ISSUED_EVENTS);
    render(<EventTimeline />);

    // "Belum ada event" because all events are ISSUED and ISSUED is hidden
    expect(screen.getByText('Belum ada event')).toBeInTheDocument();
    expect(screen.queryByText(/token diterbitkan/)).not.toBeInTheDocument();
  });

  // ── 4. Empty state ────────────────────────────────────────────────────────
  it('shows Indonesian empty-state when data array is empty', () => {
    mockOk([]);
    render(<EventTimeline />);
    expect(screen.getByText('Belum ada event')).toBeInTheDocument();
  });

  // ── 5. Loading state ──────────────────────────────────────────────────────
  it('shows loading label', () => {
    useEvents.mockReturnValue({ data: null, loading: true, error: null });
    render(<EventTimeline />);
    expect(screen.getByText('Memuat event…')).toBeInTheDocument();
  });

  // ── 6. Error state ────────────────────────────────────────────────────────
  it('shows Indonesian error message', () => {
    useEvents.mockReturnValue({ data: null, loading: false, error: 'fetch failed' });
    render(<EventTimeline />);
    expect(screen.getByText(/Event tidak tersedia: fetch failed/)).toBeInTheDocument();
  });

  // ── 7. Malformed data → ErrorBoundary isolates panel ─────────────────────
  // The component does `rawEvents = data?.data ?? []` and then passes it to
  // `aggregateIssuedEvents`. If data.data is a plain object (not null/undefined,
  // so ?? [] doesn't fire, but also not an array), the `for...of` loop in
  // aggregateIssuedEvents throws "is not iterable" → ErrorBoundary catches it.
  it('shows "Panel unavailable" via ErrorBoundary on completely malformed data', () => {
    useEvents.mockReturnValue({
      data: { data: { notAnArray: true }, total: 1 },   // plain object — for...of throws
      loading: false,
      error: null,
    });

    const restore = suppressConsoleError();
    render(
      <ErrorBoundary>
        <EventTimeline />
      </ErrorBoundary>,
    );
    restore();

    expect(screen.getByText('⚠️ Panel unavailable')).toBeInTheDocument();
  });
});
