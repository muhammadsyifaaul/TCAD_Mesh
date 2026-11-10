/**
 * dashboard/src/components/__tests__/HoneytokenPanel.test.jsx
 *
 * Unit tests for HoneytokenPanel using vitest + @testing-library/react + jsdom.
 *
 * Strategy: mock ../hooks so useHoneytokens() returns controlled data.
 * No network, no DOM event loop — hermetic.
 *
 * Test cases:
 *   1. Objects fixture   — renders token codes, identities, AKTIF badges
 *   2. Empty list        — renders Indonesian empty-state message
 *   3. Strings fixture   — old-contract strings are normalised without crash
 *   4. Malformed fixture — ErrorBoundary catches render error → "Panel unavailable"
 *   5. Old key={tok} bug — using an object as key causes React error #31;
 *                          ErrorBoundary shows "Panel unavailable"
 *   6. Loading state     — shows Indonesian loading label
 *   7. Error state       — shows Indonesian error label
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

import { ErrorBoundary } from '../ErrorBoundary';

// ── Mock the hooks module so we control what useHoneytokens returns ──────────
vi.mock('../../hooks', () => ({
  useHoneytokens: vi.fn(),
}));

import { HoneytokenPanel } from '../HoneytokenPanel';
import { useHoneytokens } from '../../hooks';

// ── Fixtures ─────────────────────────────────────────────────────────────────

const OBJECTS_FIXTURE = [
  {
    token:      'DOC-aabbccddeeff',
    session_id: 'sess-001',
    identity:   'atk-dev-1',        // ≤ 16 chars — no truncation ellipsis
    issued_at:  '2026-11-07T10:00:00Z',
  },
  {
    token:      'DOC-112233445566',
    session_id: 'sess-002',
    identity:   'atk-dev-2',
    issued_at:  '2026-11-07T10:01:00Z',
  },
];

const STRINGS_FIXTURE = ['DOC-aabbccddeeff', 'DOC-112233445566'];

// ── Helpers ───────────────────────────────────────────────────────────────────

function mockHook(tokens, { loading = false, error = null } = {}) {
  useHoneytokens.mockReturnValue({ data: { tokens }, loading, error });
}

function suppressConsoleError() {
  const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
  return () => spy.mockRestore();
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('HoneytokenPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── 1. Objects fixture ───────────────────────────────────────────────────
  it('renders token codes, identities, and AKTIF badges for objects fixture', () => {
    mockHook(OBJECTS_FIXTURE);
    render(<HoneytokenPanel />);

    expect(screen.getByText('DOC-aabbccddeeff')).toBeInTheDocument();
    expect(screen.getByText('DOC-112233445566')).toBeInTheDocument();

    // Identities visible via title attribute on the span
    expect(screen.getByTitle('atk-dev-1')).toBeInTheDocument();
    expect(screen.getByTitle('atk-dev-2')).toBeInTheDocument();

    // AKTIF badge (Indonesian) should appear once per token
    const badges = screen.getAllByText('AKTIF');
    expect(badges).toHaveLength(2);

    // Count chip
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  // ── 2. Empty list ────────────────────────────────────────────────────────
  it('shows the Indonesian empty-state message when tokens array is empty', () => {
    mockHook([]);
    render(<HoneytokenPanel />);

    expect(screen.getByText('Tidak ada honeytoken aktif')).toBeInTheDocument();
    expect(screen.queryByText('AKTIF')).not.toBeInTheDocument();
  });

  // ── 3. Strings fixture (old contract, defensive normalise) ───────────────
  it('handles old-contract strings without crashing and renders token text', () => {
    mockHook(STRINGS_FIXTURE);
    expect(() => render(<HoneytokenPanel />)).not.toThrow();

    expect(screen.getByText('DOC-aabbccddeeff')).toBeInTheDocument();
    expect(screen.getByText('DOC-112233445566')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  // ── 4. ErrorBoundary catches render errors → "Panel unavailable" ─────────
  it('shows "Panel unavailable" via ErrorBoundary when hook returns invalid tokens', () => {
    // tokens is an object (not array) — .map() throws TypeError
    useHoneytokens.mockReturnValue({
      data:    { tokens: { invalid: true } },
      loading: false,
      error:   null,
    });

    const restore = suppressConsoleError();
    render(
      <ErrorBoundary>
        <HoneytokenPanel />
      </ErrorBoundary>,
    );
    restore();

    expect(screen.getByText('⚠️ Panel unavailable')).toBeInTheDocument();
    expect(screen.queryByText('AKTIF')).not.toBeInTheDocument();
  });

  // ── 5. Old key={tok} bug proof ───────────────────────────────────────────
  // The original bug: key={tok} where tok is an object → React error #31.
  // Reproduced with a minimal inline component; ErrorBoundary must catch it.
  it('proves key={tok} on an object causes React to throw (old bug reproduced)', () => {
    function BuggyPanel({ tokens }) {
      return (
        <ul>
          {tokens.map((tok) => (
            <li key={tok}>{tok}</li>
          ))}
        </ul>
      );
    }

    const restore = suppressConsoleError();
    render(
      <ErrorBoundary>
        <BuggyPanel tokens={OBJECTS_FIXTURE} />
      </ErrorBoundary>,
    );
    restore();

    expect(screen.getByText('⚠️ Panel unavailable')).toBeInTheDocument();
  });

  // ── 6. Loading state ─────────────────────────────────────────────────────
  it('shows Indonesian loading indicator while data is being fetched', () => {
    useHoneytokens.mockReturnValue({ data: null, loading: true, error: null });
    render(<HoneytokenPanel />);
    expect(screen.getByText('Memuat…')).toBeInTheDocument();
  });

  // ── 7. Error state ───────────────────────────────────────────────────────
  it('shows Indonesian error message when hook returns an error', () => {
    useHoneytokens.mockReturnValue({ data: null, loading: false, error: 'Network timeout' });
    render(<HoneytokenPanel />);
    expect(screen.getByText(/Tidak tersedia: Network timeout/)).toBeInTheDocument();
  });
});
