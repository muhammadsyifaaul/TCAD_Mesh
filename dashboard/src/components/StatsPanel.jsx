/**
 * StatsPanel — aggregate counters at a glance.
 * Panel title and metric labels in Indonesian; event-type names stay in English.
 */
import React from 'react';
import { useStats } from '../hooks';
import { Card, Metric, Label } from './ui';

const SEVERITY_COLOR = {
  CANARY_HIT:        '#f87171',
  ENUM_DETECTED:     '#fb923c',
  QUARANTINED:       '#facc15',
  HONEYTOKEN_REUSED: '#e879f9',
  TARPIT_ACTIVE:     '#60a5fa',
  TARPIT_SATURATED:  '#818cf8',
  HONEYTOKEN_ISSUED: '#22d3ee',
};

export function StatsPanel() {
  const { data, error, loading } = useStats();

  if (loading) return <Card><Label>Memuat statistik…</Label></Card>;
  if (error)   return <Card><Label style={{ color: '#f87171' }}>Statistik tidak tersedia: {error}</Label></Card>;

  const {
    total_events      = 0,
    events_by_type    = {},
    active_quarantines = 0,
    active_honeytokens = 0,
    honeytokens_issued_total = null,
    honeytokens_reused_total = null,
    uptime_seconds,
  } = data;

  const topTypes = Object.entries(events_by_type)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 7);

  return (
    <Card>
      <h2 style={styles.heading}>Statistik Sistem</h2>
      <div style={styles.grid}>
        <MetricTile label="Total Event"          value={total_events}        />
        <MetricTile label="Karantina Aktif"      value={active_quarantines}  color="#facc15" />
        {/* "Active Honeytokens" = unique token values registered in the registry.
            One quarantined identity always produces one unique token (HMAC-seeded),
            so this equals the number of distinct attackers served honeypot data.
            honeytokens_issued_total = count of HONEYTOKEN_ISSUED events (≥ active,
            because the same identity can hit many endpoints and re-issue the same token). */}
        <HoneytokenTile
          active={active_honeytokens}
          issuedEvents={honeytokens_issued_total}
          reusedEvents={honeytokens_reused_total}
        />
        <MetricTile label="Uptime"               value={fmtUptime(uptime_seconds)} />
      </div>

      {topTypes.length > 0 && (
        <>
          <Label style={{ marginTop: 16 }}>Event per Tipe</Label>
          <div style={styles.typeGrid}>
            {topTypes.map(([type, count]) => (
              <div key={type} style={styles.typePill}>
                <span style={{ ...styles.dot, background: SEVERITY_COLOR[type] || '#6b7280' }} />
                <span style={styles.typeLabel}>{type}</span>
                <span style={styles.typeCount}>{count}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </Card>
  );
}

/** Standard metric tile */
function MetricTile({ label, value, color = '#e2e8f0' }) {
  return (
    <div style={styles.tile}>
      <Metric style={{ color }}>{value ?? '—'}</Metric>
      <Label>{label}</Label>
    </div>
  );
}

/**
 * Honeytoken tile — shows three distinct counts with clearly distinct labels.
 *
 * Definitions (documented in docs/architecture.md):
 *   Token unik (terdaftar):  unique token values in the honeytoken registry (active=1)
 *                            = number of distinct quarantined identities served honeypot data
 *   Penerbitan (event):      count of HONEYTOKEN_ISSUED events (one per honeypot response).
 *                            Can be >> "Token unik" because one identity hitting 30 endpoints
 *                            fires 30 events but registers only 1 token (INSERT OR IGNORE).
 *   digunakan ulang:         count of HONEYTOKEN_REUSED detection events
 *
 * "Token unik" ≤ "Penerbitan (event)" — always, by design.
 */
function HoneytokenTile({ active, issuedEvents, reusedEvents }) {
  const hasDetail = issuedEvents !== null && issuedEvents !== undefined;
  return (
    <div style={{ ...styles.tile, gridColumn: 'span 1' }}>
      <Metric style={{ color: '#a78bfa' }}>{active ?? '—'}</Metric>
      <Label>Token unik (terdaftar)</Label>
      {hasDetail && (
        <div style={styles.htDetail}>
          <span style={styles.htRow}>
            <span style={{ color: '#22d3ee' }}>↑ {issuedEvents}</span>
            <span style={styles.htHint}> Penerbitan (event)</span>
          </span>
          {reusedEvents > 0 && (
            <span style={styles.htRow}>
              <span style={{ color: '#e879f9' }}>⚡ {reusedEvents}</span>
              <span style={styles.htHint}> digunakan ulang</span>
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function fmtUptime(sec) {
  if (!sec) return '—';
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  if (h > 0) return `${h}j ${m}m`;
  if (m > 0) return `${m}m ${s}d`;
  return `${s}d`;
}

const styles = {
  heading:  { margin: '0 0 16px', fontSize: 14, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 1 },
  grid:     { display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 12 },
  tile:     { background: '#1e293b', borderRadius: 8, padding: '12px 16px' },
  typeGrid: { display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 },
  typePill: { display: 'flex', alignItems: 'center', gap: 6, background: '#1e293b', borderRadius: 6, padding: '4px 10px' },
  dot:      { width: 8, height: 8, borderRadius: '50%', flexShrink: 0 },
  typeLabel:{ fontSize: 11, color: '#94a3b8' },
  typeCount:{ fontSize: 13, fontWeight: 700, color: '#e2e8f0', marginLeft: 4 },
  htDetail: { marginTop: 6, display: 'flex', flexDirection: 'column', gap: 2 },
  htRow:    { fontSize: 11 },
  htHint:   { color: '#64748b' },
};
