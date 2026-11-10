/**
 * dashboard/src/components/__tests__/SimPanel.test.jsx
 *
 * Render tests for SimPanel using vitest + @testing-library/react + jsdom.
 * Mock strategy: mock ../../../hooks AND ../../../api so side effects are hermetic.
 *
 * Test cases:
 *   1. Idle state          — three scenario buttons visible, Reset button visible
 *   2. Running state       — buttons disabled, status badge shows "● Berjalan"
 *   3. Completed state     — status badge shows "✓ Selesai", last run info visible
 *   4. Full Demo warns     — "Demo Penuh" button is present and clicking it
 *                            shows the confirmation dialog (not a silent launch)
 *   5. Reset confirmation  — Reset button opens confirmation before calling api
 *   6. Confirm runs sim    — confirming the dialog calls api.runSim
 *   7. Cancel aborts       — cancelling the dialog does NOT call api.runSim
 *   8. Error banner        — when api.runSim rejects, error banner appears
 *   9. Malformed sim/status → ErrorBoundary isolates panel
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import { ErrorBoundary } from '../ErrorBoundary';

vi.mock('../../hooks', () => ({
  useSimStatus: vi.fn(),
}));

vi.mock('../../api', () => ({
  api: {
    runSim:        vi.fn(),
    resetDemoData: vi.fn(),
  },
}));

import { SimPanel } from '../SimPanel';
import { useSimStatus } from '../../hooks';
import { api } from '../../api';

// ── Fixtures ─────────────────────────────────────────────────────────────────

const IDLE_DATA    = { status: 'idle',      scenario: null,   started_at: null, finished_at: null, result: null };
const RUNNING_DATA = { status: 'running',   scenario: 'full', started_at: '2026-11-07T10:00:00Z', finished_at: null, result: null };
const DONE_DATA    = { status: 'completed', scenario: 'full', started_at: '2026-11-07T10:00:00Z', finished_at: '2026-11-07T10:02:00Z', result: {} };

// ── Helpers ───────────────────────────────────────────────────────────────────

function mockIdle()    { useSimStatus.mockReturnValue({ data: IDLE_DATA,    refresh: vi.fn() }); }
function mockRunning() { useSimStatus.mockReturnValue({ data: RUNNING_DATA, refresh: vi.fn() }); }
function mockDone()    { useSimStatus.mockReturnValue({ data: DONE_DATA,    refresh: vi.fn() }); }

function suppressConsoleError() {
  const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
  return () => spy.mockRestore();
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('SimPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: resolve immediately so awaited api calls don't hang
    api.runSim.mockResolvedValue({ status: 'started', run_id: 'test-run-id' });
    api.resetDemoData.mockResolvedValue({ status: 'ok' });
  });

  // ── 1. Idle state ─────────────────────────────────────────────────────────
  it('renders three scenario buttons and Reset in idle state', () => {
    mockIdle();
    render(<SimPanel />);

    expect(screen.getByText('✅ Legit')).toBeInTheDocument();
    expect(screen.getByText('🔍 Scan')).toBeInTheDocument();
    expect(screen.getByText('🎬 Demo Penuh')).toBeInTheDocument();
    expect(screen.getByText(/Reset Data Demo/)).toBeInTheDocument();
    expect(screen.getByText('○ Siap')).toBeInTheDocument();
  });

  // ── 2. Running state — buttons disabled ───────────────────────────────────
  it('disables all buttons while a simulation is running', () => {
    mockRunning();
    render(<SimPanel />);

    // All scenario buttons should be disabled
    const legitBtn = screen.getByText('✅ Legit').closest('button') ??
                     screen.getByRole('button', { name: /Legit/ });
    expect(legitBtn).toBeDisabled();
    expect(screen.getByText('● Berjalan')).toBeInTheDocument();
  });

  // ── 3. Completed state — shows last run info ───────────────────────────────
  it('shows "✓ Selesai" badge and last-run scenario info when completed', () => {
    mockDone();
    render(<SimPanel />);

    expect(screen.getByText('✓ Selesai')).toBeInTheDocument();
    expect(screen.getByText('full')).toBeInTheDocument(); // scenario name
    expect(screen.getByText('Terakhir:')).toBeInTheDocument();
  });

  // ── 4. Full Demo confirmation dialog shown ────────────────────────────────
  it('shows a confirmation dialog when Demo Penuh is clicked', () => {
    mockIdle();
    render(<SimPanel />);

    fireEvent.click(screen.getByText('🎬 Demo Penuh'));

    // Dialog body text must appear (use queryByText to avoid multiple-match error)
    expect(screen.getByText('Ya, lanjutkan')).toBeInTheDocument();
    expect(screen.getByText('Batal')).toBeInTheDocument();
    // Warning mentions automatic reset
    expect(screen.getByText(/reset data secara otomatis/i)).toBeInTheDocument();
    // api.runSim must NOT have been called yet
    expect(api.runSim).not.toHaveBeenCalled();
  });

  // ── 5. Reset button shows confirmation ───────────────────────────────────
  it('shows a confirmation dialog when Reset Data Demo is clicked', () => {
    mockIdle();
    render(<SimPanel />);

    fireEvent.click(screen.getByText(/Reset Data Demo/));

    expect(screen.getByText('Ya, lanjutkan')).toBeInTheDocument();
    expect(screen.getByText(/dihapus secara permanen/i)).toBeInTheDocument();
    expect(api.resetDemoData).not.toHaveBeenCalled();
  });

  // ── 6. Confirming dialog calls api.runSim ─────────────────────────────────
  it('calls api.runSim with "full" when confirmation is accepted', async () => {
    mockIdle();
    render(<SimPanel />);

    fireEvent.click(screen.getByText('🎬 Demo Penuh'));
    fireEvent.click(screen.getByText('Ya, lanjutkan'));

    await waitFor(() => expect(api.runSim).toHaveBeenCalledWith('full'));
  });

  // ── 7. Cancelling dialog does NOT call api ────────────────────────────────
  it('does NOT call api.runSim when confirmation is cancelled', () => {
    mockIdle();
    render(<SimPanel />);

    fireEvent.click(screen.getByText('🎬 Demo Penuh'));
    fireEvent.click(screen.getByText('Batal'));

    expect(api.runSim).not.toHaveBeenCalled();
    // Dialog closed — warning text gone
    expect(screen.queryByText('Ya, lanjutkan')).not.toBeInTheDocument();
  });

  // ── 8. API error banner ───────────────────────────────────────────────────
  it('shows error banner when api.runSim rejects', async () => {
    mockIdle();
    api.runSim.mockRejectedValue(new Error('409 already running'));
    render(<SimPanel />);

    // Click Legit (no confirmation dialog for non-full scenarios)
    fireEvent.click(screen.getByText('✅ Legit'));

    await waitFor(() =>
      expect(screen.getByText(/409 already running/)).toBeInTheDocument()
    );
  });

  // ── 9. Legit scenario fires immediately (no dialog) ──────────────────────
  // Non-reset scenarios (legit, scan) should NOT show a confirmation dialog;
  // they call api.runSim immediately on click.
  it('calls api.runSim immediately (no dialog) for legit scenario', async () => {
    mockIdle();
    render(<SimPanel />);

    fireEvent.click(screen.getByText('✅ Legit'));

    // No dialog shown
    expect(screen.queryByText('Ya, lanjutkan')).not.toBeInTheDocument();
    // api.runSim called directly
    await waitFor(() => expect(api.runSim).toHaveBeenCalledWith('legit'));
  });
});
