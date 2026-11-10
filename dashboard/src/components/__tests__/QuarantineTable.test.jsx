/**
 * dashboard/src/components/__tests__/QuarantineTable.test.jsx
 *
 * Render tests for QuarantineTable using vitest + @testing-library/react + jsdom.
 *
 * Test cases:
 *   1. Populated table  — identity, reason badge, countdown, Lepas button visible
 *   2. Multiple entries — count badge shows "2"
 *   3. Empty state      — "Tidak ada karantina aktif" empty message
 *   4. Countdown colors — sec < 60 renders in red, sec > 300 renders in green
 *   5. Release button   — clicking "Lepas" calls api.releaseQuarantine
 *   6. Release in-progress — button changes to "Melepas…" while awaiting api
 *   7. Release error    — error banner appears when release fails
 *   8. Loading state    — "Memuat…" label
 *   9. Error state      — "Tidak tersedia: …" label
 *  10. Malformed data   — ErrorBoundary isolates panel
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import { ErrorBoundary } from '../ErrorBoundary';

vi.mock('../../hooks', () => ({
  useQuarantine: vi.fn(),
}));

vi.mock('../../api', () => ({
  api: {
    releaseQuarantine: vi.fn(),
  },
}));

import { QuarantineTable } from '../QuarantineTable';
import { useQuarantine } from '../../hooks';
import { api } from '../../api';

// ── Fixtures ─────────────────────────────────────────────────────────────────

function makeEntry(overrides) {
  return {
    identity:         'attacker-01',
    quarantined_at:   '2026-11-07T10:00:00Z',
    expires_at:       '2026-11-07T10:15:00Z',
    remaining_ttl_sec: 600,
    reason:           'CANARY_HIT',
    ...overrides,
  };
}

const ONE_ENTRY  = { epoch: 1, data: [makeEntry()] };
const TWO_ENTRIES = {
  epoch: 1,
  data: [
    makeEntry({ identity: 'attacker-01', remaining_ttl_sec: 600, reason: 'CANARY_HIT' }),
    makeEntry({ identity: 'attacker-02', remaining_ttl_sec: 45,  reason: 'ENUM_DETECTED' }),
  ],
};
const EMPTY = { epoch: 1, data: [] };

// ── Helpers ───────────────────────────────────────────────────────────────────

function mockOk(data) {
  useQuarantine.mockReturnValue({ data, loading: false, error: null, refresh: vi.fn() });
}

function suppressConsoleError() {
  const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
  return () => spy.mockRestore();
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('QuarantineTable', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.releaseQuarantine.mockResolvedValue({ identity: 'attacker-01', released: true });
  });

  // ── 1. Populated table ───────────────────────────────────────────────────
  it('renders identity, reason, countdown, and Lepas button', () => {
    mockOk(ONE_ENTRY);
    render(<QuarantineTable />);

    expect(screen.getByText('attacker-01')).toBeInTheDocument();
    expect(screen.getByText('CANARY_HIT')).toBeInTheDocument();
    // Countdown: 600 s = 10m 0s
    expect(screen.getByText(/10m/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Lepas' })).toBeInTheDocument();
  });

  // ── 2. Count badge for multiple entries ──────────────────────────────────
  it('shows count badge "2" when two entries are present', () => {
    mockOk(TWO_ENTRIES);
    render(<QuarantineTable />);

    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('attacker-01')).toBeInTheDocument();
    expect(screen.getByText('attacker-02')).toBeInTheDocument();
  });

  // ── 3. Empty state ────────────────────────────────────────────────────────
  it('shows Indonesian empty message when no entries', () => {
    mockOk(EMPTY);
    render(<QuarantineTable />);
    expect(screen.getByText('Tidak ada karantina aktif')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Lepas' })).not.toBeInTheDocument();
  });

  // ── 4. Countdown colour: < 60s renders in red ────────────────────────────
  it('renders short countdowns in red text', () => {
    mockOk({ epoch: 1, data: [makeEntry({ remaining_ttl_sec: 45 })] });
    render(<QuarantineTable />);

    // 45 s = 0m 45s — Countdown renders "45s"
    const countdown = screen.getByText('45s');
    expect(countdown).toBeInTheDocument();
    expect(countdown.style.color).toBe('rgb(248, 113, 113)'); // #f87171
  });

  // ── 5. Release button calls api ───────────────────────────────────────────
  it('calls api.releaseQuarantine when Lepas is clicked', async () => {
    mockOk(ONE_ENTRY);
    render(<QuarantineTable />);

    fireEvent.click(screen.getByRole('button', { name: 'Lepas' }));

    await waitFor(() =>
      expect(api.releaseQuarantine).toHaveBeenCalledWith('attacker-01')
    );
  });

  // ── 6. Button changes to "Melepas…" while in flight ──────────────────────
  it('shows "Melepas…" label while release is in progress', async () => {
    mockOk(ONE_ENTRY);
    // Never resolves so we can observe the in-progress state
    api.releaseQuarantine.mockReturnValue(new Promise(() => {}));
    render(<QuarantineTable />);

    fireEvent.click(screen.getByRole('button', { name: 'Lepas' }));

    expect(await screen.findByRole('button', { name: 'Melepas…' })).toBeInTheDocument();
  });

  // ── 7. Release error banner ───────────────────────────────────────────────
  it('shows error banner when release fails', async () => {
    mockOk(ONE_ENTRY);
    api.releaseQuarantine.mockRejectedValue(new Error('403 forbidden'));
    render(<QuarantineTable />);

    fireEvent.click(screen.getByRole('button', { name: 'Lepas' }));

    await waitFor(() =>
      expect(screen.getByText(/Gagal melepas attacker-01/)).toBeInTheDocument()
    );
  });

  // ── 8. Loading state ─────────────────────────────────────────────────────
  it('shows "Memuat…"', () => {
    useQuarantine.mockReturnValue({ data: null, loading: true, error: null, refresh: vi.fn() });
    render(<QuarantineTable />);
    expect(screen.getByText('Memuat…')).toBeInTheDocument();
  });

  // ── 9. Error state ────────────────────────────────────────────────────────
  it('shows Indonesian error message', () => {
    useQuarantine.mockReturnValue({ data: null, loading: false, error: 'DB error', refresh: vi.fn() });
    render(<QuarantineTable />);
    expect(screen.getByText(/Tidak tersedia: DB error/)).toBeInTheDocument();
  });

  // ── 10. Malformed data → ErrorBoundary isolates panel ────────────────────
  it('shows "Panel unavailable" for data where data.data is not iterable', () => {
    // data.data is a string — entries = data?.data ?? [] → 'epoch:1,data:...' is a string;
    // .map() on a string gives each character. Render expects objects with .identity etc.
    // A simpler crash: set data itself to null but loading=false → entries = null?.data ?? [] = []
    // → empty. For a real crash, give data.data a non-iterable value that slips past ?? []:
    useQuarantine.mockReturnValue({
      data:    { epoch: 1, data: { 0: makeEntry() } },   // object not array — .map() throws
      loading: false,
      error:   null,
      refresh: vi.fn(),
    });

    const restore = suppressConsoleError();
    render(
      <ErrorBoundary>
        <QuarantineTable />
      </ErrorBoundary>,
    );
    restore();

    expect(screen.getByText('⚠️ Panel unavailable')).toBeInTheDocument();
  });
});
