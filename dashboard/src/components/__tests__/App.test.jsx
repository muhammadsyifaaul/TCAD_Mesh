/**
 * dashboard/src/components/__tests__/App.test.jsx
 *
 * Smoke-test + isolation test for the root <App /> component.
 *
 * Strategy: mock ALL hooks so no real fetching happens, then:
 *   1. Smoke test      — header, footer, all panel headings render
 *   2. Mode badge      — "Mode 1 · Pertahanan Aktif" badge visible
 *   3. Panel isolation — crashing StatsPanel does NOT blank the whole app;
 *                        footer and other headings remain
 *
 * We deliberately do NOT test every panel's internals here (those have
 * dedicated test files). We only test the layout and ErrorBoundary isolation.
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

// ── Mock ALL hooks ─────────────────────────────────────────────────────────
vi.mock('../../hooks', () => ({
  useStats:       vi.fn(),
  useEvents:      vi.fn(),
  useQuarantine:  vi.fn(),
  useHoneytokens: vi.fn(),
  useSimStatus:   vi.fn(),
}));

// Also mock api so SimPanel's reset/run calls are silent
vi.mock('../../api', () => ({
  api: {
    runSim:            vi.fn(),
    resetDemoData:     vi.fn(),
    releaseQuarantine: vi.fn(),
  },
}));

import App from '../../App';
import { useStats, useEvents, useQuarantine, useHoneytokens, useSimStatus } from '../../hooks';

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Set all hooks to loading so panels show their skeleton labels */
function mockAllLoading() {
  const loadingPoll = { data: null, loading: true, error: null, refresh: vi.fn() };
  useStats.mockReturnValue(loadingPoll);
  useEvents.mockReturnValue(loadingPoll);
  useQuarantine.mockReturnValue(loadingPoll);
  useHoneytokens.mockReturnValue(loadingPoll);
  useSimStatus.mockReturnValue(loadingPoll);
}

/** Set all hooks to empty/idle data */
function mockAllIdle() {
  useStats.mockReturnValue({ data: { total_events: 0, events_by_type: {}, active_quarantines: 0, active_honeytokens: 0, honeytokens_issued_total: 0, honeytokens_reused_total: 0, uptime_seconds: 0 }, loading: false, error: null });
  useEvents.mockReturnValue({ data: { data: [], total: 0 }, loading: false, error: null });
  useQuarantine.mockReturnValue({ data: { epoch: 0, data: [] }, loading: false, error: null, refresh: vi.fn() });
  useHoneytokens.mockReturnValue({ data: { tokens: [] }, loading: false, error: null });
  useSimStatus.mockReturnValue({ data: { status: 'idle', scenario: null, started_at: null, finished_at: null, result: null }, refresh: vi.fn() });
}

function suppressConsoleError() {
  const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
  return () => spy.mockRestore();
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('App', () => {
  beforeEach(() => vi.clearAllMocks());

  // ── 1. Smoke test ─────────────────────────────────────────────────────────
  it('renders header, footer, and all panel headings in loading state', () => {
    mockAllLoading();
    render(<App />);

    // Brand
    expect(screen.getByText('TCAD Mesh')).toBeInTheDocument();
    expect(screen.getByText('Dasbor Operator')).toBeInTheDocument();

    // Footer
    expect(screen.getByText(/Kartika Cyber Hackathon 2026/)).toBeInTheDocument();

    // Panel headings (from each component's h2)
    // StatsPanel shows "Memuat statistik…" (loading), SimPanel shows "Kontrol Simulasi"
    expect(screen.getByText('Kontrol Simulasi')).toBeInTheDocument();
    expect(screen.getByText('Linimasa Event')).toBeInTheDocument();
    expect(screen.getByText('Karantina')).toBeInTheDocument();
    expect(screen.getByText('Honeytoken')).toBeInTheDocument();
  });

  // ── 2. Mode badge ─────────────────────────────────────────────────────────
  it('shows the "Mode 1 · Pertahanan Aktif" badge', () => {
    mockAllLoading();
    render(<App />);
    expect(screen.getByText('Mode 1 · Pertahanan Aktif')).toBeInTheDocument();
  });

  // ── 3. Panel isolation — crashing StatsPanel blanks only itself ───────────
  // Force StatsPanel to crash: loading=false, error=null, data=null →
  // the component skips both early-return guards and tries to destructure null
  // → `const { total_events = 0 } = null` → TypeError: Cannot destructure property
  // 'total_events' of null → ErrorBoundary catches it.
  // Footer and other panels must still render.
  it('isolates a crashing StatsPanel without blanking the whole app', () => {
    useStats.mockReturnValue({ data: null, loading: false, error: null });
    useEvents.mockReturnValue({ data: { data: [], total: 0 }, loading: false, error: null });
    useQuarantine.mockReturnValue({ data: { epoch: 0, data: [] }, loading: false, error: null, refresh: vi.fn() });
    useHoneytokens.mockReturnValue({ data: { tokens: [] }, loading: false, error: null });
    useSimStatus.mockReturnValue({ data: { status: 'idle', scenario: null, started_at: null, finished_at: null, result: null }, refresh: vi.fn() });

    const restore = suppressConsoleError();
    render(<App />);
    restore();

    // StatsPanel's ErrorBoundary shows "Panel unavailable" (regex to handle emoji encoding)
    expect(screen.getByText(/Panel unavailable/)).toBeInTheDocument();

    // Other panels and chrome still render
    expect(screen.getByText(/Kartika Cyber Hackathon 2026/)).toBeInTheDocument();
    expect(screen.getByText('Kontrol Simulasi')).toBeInTheDocument();
    expect(screen.getByText('Linimasa Event')).toBeInTheDocument();
  });

  // ── 4. All idle — no blank panels ─────────────────────────────────────────
  it('renders all panels without crashing when all data is idle/empty', () => {
    mockAllIdle();
    const restore = suppressConsoleError();
    render(<App />);
    restore();

    // No ErrorBoundary fallbacks should appear
    expect(screen.queryByText('⚠️ Panel unavailable')).not.toBeInTheDocument();

    // Footer still present
    expect(screen.getByText(/Semua data adalah waktu nyata/)).toBeInTheDocument();
  });
});
