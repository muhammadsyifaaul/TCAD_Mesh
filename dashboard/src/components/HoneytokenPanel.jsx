/**
 * HoneytokenPanel — daftar honeytoken aktif.
 * Panel title and UI labels in Indonesian; token values stay as-is.
 *
 * GET /honeytokens returns: {"tokens": [{token, session_id, identity, issued_at}, ...]}
 */
import React from 'react';
import { useHoneytokens } from '../hooks';
import { Card, Label } from './ui';

function shorten(str, max = 12) {
  if (!str) return '—';
  return str.length > max ? str.slice(0, max) + '…' : str;
}

function formatTime(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return iso;
  }
}

export function HoneytokenPanel() {
  const { data, error, loading } = useHoneytokens();
  // Defensive: tokens may be strings (old contract) or objects (new contract)
  const rawTokens = data?.tokens ?? [];
  const tokens = rawTokens.map(t => {
    if (typeof t === 'string') {
      return { token: t, session_id: '', identity: '', issued_at: '' };
    }
    return {
      token:      t.token      ?? '?',
      session_id: t.session_id ?? '',
      identity:   t.identity   ?? '',
      issued_at:  t.issued_at  ?? '',
    };
  });

  return (
    <Card>
      <div style={styles.header}>
        <h2 style={styles.heading}>
          Honeytoken
          {tokens.length > 0 && (
            <span style={styles.count}>{tokens.length}</span>
          )}
        </h2>
      </div>

      {loading && tokens.length === 0 && <Label>Memuat…</Label>}
      {error   && <Label style={{ color: '#f87171' }}>Tidak tersedia: {error}</Label>}

      {tokens.length === 0 && !loading ? (
        <div style={styles.empty}>
          <span style={styles.emptyIcon}>🍯</span>
          <Label>Tidak ada honeytoken aktif</Label>
          <Label style={{ fontSize: 11 }}>Token muncul setelah penyerang mengakses honeypot</Label>
        </div>
      ) : (
        <div style={styles.list}>
          {tokens.map((entry, i) => (
            <div key={entry.token || i} style={styles.token}>
              <span style={styles.bullet}>▸</span>
              <div style={styles.tokenInfo}>
                <code style={styles.code}>{entry.token}</code>
                <div style={styles.meta}>
                  <span style={styles.metaItem} title={entry.identity}>
                    id: {shorten(entry.identity, 16)}
                  </span>
                  {entry.session_id && (
                    <span style={styles.metaItem} title={entry.session_id}>
                      sesi: {shorten(entry.session_id, 10)}
                    </span>
                  )}
                  {entry.issued_at && (
                    <span style={styles.metaItem}>
                      {formatTime(entry.issued_at)}
                    </span>
                  )}
                </div>
              </div>
              <span style={styles.badge}>AKTIF</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

const styles = {
  header:    { display: 'flex', alignItems: 'center', marginBottom: 12 },
  heading:   { margin: 0, fontSize: 14, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 1, display: 'flex', alignItems: 'center', gap: 8 },
  count:     { background: '#0891b2', color: '#fff', borderRadius: 10, padding: '1px 8px', fontSize: 11, fontWeight: 700 },
  empty:     { display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '24px 0', gap: 6 },
  emptyIcon: { fontSize: 28 },
  list:      { display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 280, overflowY: 'auto' },
  token:     { display: 'flex', alignItems: 'flex-start', gap: 10, background: '#0c1a2e', borderRadius: 6, padding: '7px 12px', border: '1px solid #1e3a5f' },
  bullet:    { color: '#0891b2', fontSize: 10, marginTop: 4 },
  tokenInfo: { flex: 1, minWidth: 0 },
  code:      { fontFamily: 'monospace', fontSize: 13, color: '#7dd3fc' },
  meta:      { display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 3 },
  metaItem:  { fontSize: 10, color: '#64748b' },
  badge:     { fontSize: 9, fontWeight: 700, color: '#0891b2', background: '#0891b222', border: '1px solid #0891b244', borderRadius: 3, padding: '1px 6px', letterSpacing: 0.5, marginTop: 2 },
};
