/**
 * QuarantineTable — daftar karantina aktif dengan tombol Lepas,
 * dan form Karantina Manual untuk operator.
 *
 * LIMITATION: In Mode 1 the identity comes from a client-controlled
 * X-Device-ID header, so operator quarantine is only meaningful when that
 * identity comes from a trusted source (mTLS in Mode 2 or an authenticated
 * client app). Do NOT use this to claim protection against stolen devices;
 * it is an operator control that shortens the window between detection and
 * enforcement.
 *
 * Panel title and UI labels in Indonesian; event-type names stay in English.
 */
import React, { useState } from 'react';
import { useQuarantine } from '../hooks';
import { api } from '../api';
import { Card, Label } from './ui';
import { ErrorBoundary } from './ErrorBoundary';

// ── Karantina Manual form ─────────────────────────────────────────────────────

const PRESET_REASONS = [
  'OPERATOR_MANUAL',
  'CANARY_HIT',
  'ENUM_DETECTED',
  'HONEYTOKEN_REUSED',
  'Lainnya…',
];

const TTL_OPTIONS = [
  { label: '5 menit',  sec: 300 },
  { label: '15 menit', sec: 900 },
  { label: '1 jam',    sec: 3600 },
  { label: '4 jam',    sec: 14400 },
];

function ManualQuarantineForm({ onSuccess }) {
  const [identity, setIdentity]   = useState('');
  const [reason,   setReason]     = useState('OPERATOR_MANUAL');
  const [custom,   setCustom]     = useState('');
  const [ttlSec,   setTtlSec]     = useState(900);
  const [busy,     setBusy]       = useState(false);
  const [error,    setError]      = useState(null);
  const [open,     setOpen]       = useState(false);

  const effectiveReason = reason === 'Lainnya…' ? custom.trim() : reason;

  async function handleSubmit(e) {
    e.preventDefault();
    if (!identity.trim()) { setError('Identitas tidak boleh kosong.'); return; }
    if (!effectiveReason) { setError('Alasan tidak boleh kosong.'); return; }
    setBusy(true);
    setError(null);
    try {
      await api.addQuarantine(identity.trim(), effectiveReason, ttlSec);
      setIdentity(''); setReason('OPERATOR_MANUAL'); setCustom(''); setTtlSec(900);
      setOpen(false);
      onSuccess();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={fStyles.wrap}>
      <button
        data-testid="toggle-manual-form"
        onClick={() => { setOpen(o => !o); setError(null); }}
        style={fStyles.toggleBtn}
      >
        {open ? '✕ Tutup' : '+ Karantina Manual'}
      </button>

      {open && (
        <form
          data-testid="manual-quarantine-form"
          onSubmit={handleSubmit}
          style={fStyles.form}
        >
          <div style={fStyles.limitation}>
            ⚠ Karantina manual hanya efektif jika identitas berasal dari sumber
            tepercaya (misalnya mTLS Mode 2 atau autentikasi klien). Ini adalah
            kontrol operator untuk memperpendek jendela serangan, bukan perlindungan
            terhadap perangkat yang dicuri.
          </div>

          <label style={fStyles.label}>
            Identitas (Device-ID atau IP)
            <input
              data-testid="input-identity"
              type="text"
              value={identity}
              onChange={e => setIdentity(e.target.value)}
              placeholder="mis. device-123 atau 10.0.0.5"
              style={fStyles.input}
              autoFocus
            />
          </label>

          <label style={fStyles.label}>
            Alasan
            <select
              data-testid="select-reason"
              value={reason}
              onChange={e => setReason(e.target.value)}
              style={fStyles.input}
            >
              {PRESET_REASONS.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>

          {reason === 'Lainnya…' && (
            <label style={fStyles.label}>
              Alasan kustom
              <input
                data-testid="input-custom-reason"
                type="text"
                value={custom}
                onChange={e => setCustom(e.target.value)}
                placeholder="Tulis alasan…"
                style={fStyles.input}
              />
            </label>
          )}

          <label style={fStyles.label}>
            Durasi TTL
            <select
              data-testid="select-ttl"
              value={ttlSec}
              onChange={e => setTtlSec(Number(e.target.value))}
              style={fStyles.input}
            >
              {TTL_OPTIONS.map(o => (
                <option key={o.sec} value={o.sec}>{o.label}</option>
              ))}
            </select>
          </label>

          {error && (
            <div data-testid="form-error" style={fStyles.error}>{error}</div>
          )}

          <button
            data-testid="submit-quarantine"
            type="submit"
            disabled={busy}
            style={{ ...fStyles.submitBtn, opacity: busy ? 0.5 : 1 }}
          >
            {busy ? 'Mengirim…' : '🔒 Karantina Sekarang'}
          </button>
        </form>
      )}
    </div>
  );
}

const fStyles = {
  wrap:       { marginTop: 10 },
  toggleBtn:  { background: 'transparent', border: '1px solid #2563eb', borderRadius: 6, color: '#93c5fd', padding: '5px 12px', fontSize: 11, cursor: 'pointer', fontWeight: 600 },
  form:       { background: '#0a1628', border: '1px solid #1e3a5f', borderRadius: 8, padding: 12, marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 },
  limitation: { background: '#1a1600', border: '1px solid #a16207', borderRadius: 4, color: '#fde047', fontSize: 10, padding: '6px 10px', lineHeight: 1.5 },
  label:      { display: 'flex', flexDirection: 'column', gap: 3, fontSize: 11, color: '#94a3b8' },
  input:      { background: '#1e293b', border: '1px solid #334155', borderRadius: 4, color: '#e2e8f0', padding: '6px 8px', fontSize: 12, outline: 'none', marginTop: 2 },
  error:      { background: '#3b0a0a', border: '1px solid #7f1d1d', borderRadius: 4, color: '#fca5a5', fontSize: 11, padding: '6px 10px' },
  submitBtn:  { background: '#1e3a5f', border: '1px solid #2563eb', borderRadius: 6, color: '#93c5fd', padding: '8px 14px', fontSize: 12, cursor: 'pointer', fontWeight: 600 },
};

// ── Main QuarantineTable ──────────────────────────────────────────────────────

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

      {/* Manual quarantine form wrapped in ErrorBoundary so a form crash
          never blanks the whole quarantine table */}
      <ErrorBoundary>
        <ManualQuarantineForm onSuccess={refresh} />
      </ErrorBoundary>
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
