/**
 * SimPanel — kontrol simulasi + status terkini.
 * UI labels in Indonesian; scenario IDs and event names stay in English.
 *
 * Confirmation dialog is shown before:
 *   - "🎬 Demo Penuh" because Phase 0 of the scenario calls POST /reset
 *     (clears events, quarantine, honeytokens)
 *   - "🗑 Reset Data Demo" for the same reason
 * All other scenarios (legit, scan) fire immediately without confirmation.
 */
import React, { useState } from 'react';
import { useSimStatus } from '../hooks';
import { api } from '../api';
import { Card, Label } from './ui';

const SCENARIOS = [
  { id: 'legit', label: '✅ Legit',       desc: 'Lalu lintas normal — 0 peringatan diharapkan' },
  { id: 'scan',  label: '🔍 Scan',        desc: 'Probe penyerang: canary paths + enumerasi' },
  { id: 'full',  label: '🎬 Demo Penuh',  desc: 'Urutan lengkap: reset → legit → scan → reuse token → lepas karantina' },
];

/** Scenarios that reset all data as part of their flow — require confirmation */
const RESET_SCENARIOS = new Set(['full']);

const STATUS_STYLE = {
  running:   { color: '#4ade80', badge: '#14532d', label: '● Berjalan' },
  completed: { color: '#94a3b8', badge: '#1e293b', label: '✓ Selesai' },
  failed:    { color: '#f87171', badge: '#450a0a', label: '✗ Gagal' },
  idle:      { color: '#475569', badge: '#0f172a', label: '○ Siap' },
};

export function SimPanel() {
  const { data: simData, refresh } = useSimStatus();
  const [launching,       setLaunching]       = useState(null);
  const [launchError,     setLaunchError]      = useState(null);
  /** Pending action waiting for confirmation: { type: 'scenario'|'reset', id?, label, warning } */
  const [pendingAction,   setPendingAction]    = useState(null);

  const status     = simData?.status ?? 'idle';
  const isRunning  = status === 'running';
  const statusInfo = STATUS_STYLE[status] || STATUS_STYLE.idle;

  // ── Run a simulation scenario ────────────────────────────────────────────
  async function handleRun(scenario) {
    setLaunching(scenario);
    setLaunchError(null);
    try {
      await api.runSim(scenario);
      await refresh();
    } catch (e) {
      setLaunchError(e.message);
    } finally {
      setLaunching(null);
    }
  }

  // ── Scenario button click — show confirmation only for reset-class scenarios
  function onScenarioClick(sc) {
    if (RESET_SCENARIOS.has(sc.id)) {
      setPendingAction({
        type:    'scenario',
        id:      sc.id,
        label:   sc.label,
        warning: `Fase 0 dari skenario ini akan menjalankan reset data secara otomatis — semua event, karantina, dan honeytoken akan dihapus. Lanjutkan?`,
      });
    } else {
      handleRun(sc.id);
    }
  }

  // ── Reset button click ────────────────────────────────────────────────────
  function onResetClick() {
    setPendingAction({
      type:    'reset',
      label:   '🗑 Reset Data Demo',
      warning: 'Semua event, karantina, dan honeytoken akan dihapus secara permanen. Lanjutkan?',
    });
  }

  // ── Confirmation dialog confirm ───────────────────────────────────────────
  async function onConfirm() {
    const action = pendingAction;
    setPendingAction(null);
    if (action.type === 'scenario') {
      await handleRun(action.id);
    } else {
      setLaunching('reset');
      setLaunchError(null);
      try {
        await api.resetDemoData();
        window.location.reload();
      } catch (e) {
        setLaunchError(e.message);
      } finally {
        setLaunching(null);
      }
    }
  }

  function onCancel() {
    setPendingAction(null);
  }

  return (
    <Card>
      <div style={styles.header}>
        <h2 style={styles.heading}>Kontrol Simulasi</h2>
        <span style={{ ...styles.statusBadge, background: statusInfo.badge, color: statusInfo.color }}>
          {statusInfo.label}
        </span>
      </div>

      {launchError && (
        <div style={styles.errorBanner}>{launchError}</div>
      )}

      {simData && simData.scenario && (
        <div style={styles.currentRun}>
          <Label>Terakhir: <strong style={{ color: '#e2e8f0' }}>{simData.scenario}</strong></Label>
          {simData.started_at && (
            <Label style={{ fontSize: 11 }}>
              Mulai: {new Date(simData.started_at).toLocaleTimeString()}
              {simData.finished_at
                ? ` → Selesai: ${new Date(simData.finished_at).toLocaleTimeString()}`
                : ' (sedang berjalan)'}
            </Label>
          )}
        </div>
      )}

      <div style={styles.btnGrid}>
        {SCENARIOS.map(sc => (
          <button
            key={sc.id}
            onClick={() => onScenarioClick(sc)}
            disabled={isRunning || launching !== null}
            style={{
              ...styles.btn,
              ...(sc.id === 'full' ? styles.btnPrimary : {}),
              opacity: (isRunning || launching) ? 0.45 : 1,
              cursor: (isRunning || launching) ? 'not-allowed' : 'pointer',
            }}
            title={sc.desc}
          >
            {launching === sc.id ? 'Memulai…' : sc.label}
          </button>
        ))}
      </div>

      <Label style={{ marginTop: 10, fontSize: 11 }}>
        Simulasi hanya menargetkan kontainer lokal. Pantau Linimasa Event untuk peringatan.
      </Label>

      <button
        onClick={onResetClick}
        disabled={launching === 'reset'}
        style={{
          ...styles.btn,
          background: '#3b1d1d',
          borderColor: '#7f1d1d',
          color: '#fca5a5',
          marginTop: 10,
          width: '100%',
          opacity: launching === 'reset' ? 0.5 : 1,
          cursor: launching === 'reset' ? 'not-allowed' : 'pointer',
        }}
      >
        {launching === 'reset' ? 'Mereset…' : '🗑 Reset Data Demo'}
      </button>

      {/* ── Confirmation dialog ──────────────────────────────────────────── */}
      {pendingAction && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Konfirmasi"
          style={styles.dialogOverlay}
        >
          <div style={styles.dialog}>
            <div style={styles.dialogTitle}>⚠️ {pendingAction.label}</div>
            <p style={styles.dialogBody}>{pendingAction.warning}</p>
            <div style={styles.dialogBtns}>
              <button
                onClick={onConfirm}
                style={{ ...styles.btn, ...styles.btnDanger }}
                aria-label="Ya, lanjutkan"
              >
                Ya, lanjutkan
              </button>
              <button
                onClick={onCancel}
                style={{ ...styles.btn, ...styles.btnCancel }}
                aria-label="Batal"
              >
                Batal
              </button>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}

const styles = {
  header:      { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 },
  heading:     { margin: 0, fontSize: 14, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 1 },
  statusBadge: { fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: 20 },
  errorBanner: { background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 6, color: '#fca5a5', padding: '8px 12px', marginBottom: 10, fontSize: 12 },
  currentRun:  { background: '#0f172a', borderRadius: 6, padding: '8px 12px', marginBottom: 12, display: 'flex', flexDirection: 'column', gap: 4 },
  btnGrid:     { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 },
  btn: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 8,
    color: '#cbd5e1', padding: '12px 8px', fontSize: 13, fontWeight: 600,
    transition: 'background 0.15s', cursor: 'pointer',
  },
  btnPrimary: { background: '#1e3a5f', borderColor: '#2563eb', color: '#93c5fd' },
  btnDanger:  { background: '#450a0a', borderColor: '#dc2626', color: '#fca5a5', flex: 1 },
  btnCancel:  { background: '#1e293b', borderColor: '#334155', color: '#94a3b8', flex: 1 },
  // Dialog overlay — sits inside the Card, covers only this panel
  dialogOverlay: {
    position: 'absolute', inset: 0, background: 'rgba(2,6,23,0.85)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    borderRadius: 12, zIndex: 10,
  },
  dialog: {
    background: '#0f172a', border: '1px solid #7f1d1d', borderRadius: 10,
    padding: '20px 24px', maxWidth: 320, width: '100%',
  },
  dialogTitle: { fontSize: 14, fontWeight: 700, color: '#fca5a5', marginBottom: 10 },
  dialogBody:  { fontSize: 12, color: '#94a3b8', marginBottom: 16, lineHeight: 1.5 },
  dialogBtns:  { display: 'flex', gap: 10 },
};
