/**
 * QuarantineTable — daftar karantina aktif dengan tombol Lepas.
 * Panel title and UI labels in Indonesian; event-type names stay in English.
 */
import React, { useState } from 'react';
import { useQuarantine } from '../hooks';
import { api } from '../api';
import { Card, Label } from './ui';

export function QuarantineTable() {
  const { data, error, loading, refresh } = useQuarantine();
  const [releasing, setReleasing] = useState(null);
  const [releaseError, setReleaseError] = useState(null);

  const entries = data?.data ?? [];

  async function handleRelease(identity) {
    setReleasing(identity);
    setReleaseError(null);
    try {
      await api.releaseQuarantine(identity);
      await refresh();
    } catch (e) {
      setReleaseError(`Gagal melepas ${identity}: ${e.message}`);
    } finally {
      setReleasing(null);
    }
  }

  return (
    <Card>
      <div style={styles.header}>
        <h2 style={styles.heading}>
          Karantina
          {entries.length > 0 && (
            <span style={styles.count}>{entries.length}</span>
          )}
        </h2>
      </div>

      {releaseError && (
        <div style={styles.errorBanner}>{releaseError}</div>
      )}

      {loading && entries.length === 0 && <Label>Memuat…</Label>}
      {error   && <Label style={{ color: '#f87171' }}>Tidak tersedia: {error}</Label>}

      {entries.length === 0 && !loading ? (
        <div style={styles.empty}>
          <span style={styles.emptyIcon}>🛡️</span>
          <Label>Tidak ada karantina aktif</Label>
        </div>
      ) : (
        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                {['Identitas', 'Alasan', 'Berakhir dalam', 'Aksi'].map(h => (
                  <th key={h} style={styles.th}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {entries.map(entry => (
                <tr key={entry.identity} style={styles.tr}>
                  <td style={styles.td}>
                    <code style={styles.code}>{entry.identity}</code>
                  </td>
                  <td style={styles.td}>
                    <span style={{ ...styles.reason, ...reasonStyle(entry.reason) }}>
                      {entry.reason}
                    </span>
                  </td>
                  <td style={styles.td}>
                    <Countdown sec={entry.remaining_ttl_sec} />
                  </td>
                  <td style={styles.td}>
                    <button
                      onClick={() => handleRelease(entry.identity)}
                      disabled={releasing === entry.identity}
                      style={{
                        ...styles.releaseBtn,
                        opacity: releasing === entry.identity ? 0.5 : 1,
                      }}
                    >
                      {releasing === entry.identity ? 'Melepas…' : 'Lepas'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function Countdown({ sec }) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  const color = sec < 60 ? '#f87171' : sec < 300 ? '#fb923c' : '#4ade80';
  return (
    <span style={{ color, fontFamily: 'monospace', fontSize: 13 }}>
      {m > 0 ? `${m}m ` : ''}{s}s
    </span>
  );
}

function reasonStyle(reason) {
  const map = {
    CANARY_HIT:        { background: '#7f1d1d44', color: '#fca5a5' },
    HONEYTOKEN_REUSED: { background: '#4a044e44', color: '#f0abfc' },
    ENUM_DETECTED:     { background: '#431407', color: '#fdba74' },
  };
  return map[reason] || { background: '#1e293b', color: '#94a3b8' };
}

const styles = {
  header:     { display: 'flex', alignItems: 'center', marginBottom: 12 },
  heading:    { margin: 0, fontSize: 14, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 1, display: 'flex', alignItems: 'center', gap: 8 },
  count:      { background: '#dc2626', color: '#fff', borderRadius: 10, padding: '1px 8px', fontSize: 11, fontWeight: 700 },
  errorBanner:{ background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 6, color: '#fca5a5', padding: '8px 12px', marginBottom: 10, fontSize: 12 },
  empty:      { display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '24px 0', gap: 8 },
  emptyIcon:  { fontSize: 28 },
  tableWrap:  { overflowX: 'auto' },
  table:      { width: '100%', borderCollapse: 'collapse', fontSize: 12 },
  th:         { textAlign: 'left', padding: '6px 10px', color: '#64748b', borderBottom: '1px solid #1e293b', fontWeight: 600, fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5 },
  tr:         { borderBottom: '1px solid #0f172a' },
  td:         { padding: '8px 10px', color: '#cbd5e1', verticalAlign: 'middle' },
  code:       { fontFamily: 'monospace', fontSize: 12, color: '#93c5fd' },
  reason:     { borderRadius: 4, padding: '2px 8px', fontSize: 10, fontWeight: 700 },
  releaseBtn: { background: '#166534', border: '1px solid #15803d', borderRadius: 5, color: '#4ade80', padding: '4px 12px', fontSize: 11, cursor: 'pointer', fontWeight: 600, transition: 'opacity 0.15s' },
};
