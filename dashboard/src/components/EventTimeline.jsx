/**
 * EventTimeline — umpan event waktu nyata, polling setiap 2 detik.
 *
 * HONEYTOKEN_ISSUED events are collapsed into one aggregated row per (identity, minute)
 * so they don't flood the timeline. The raw events are still stored in the API —
 * only the display is aggregated. Users can toggle ISSUED events back on with the
 * "ISSUED" filter chip.
 *
 * Row colors are driven strictly by severity:
 *   high  → red background   (CANARY_HIT, HONEYTOKEN_REUSED, QUARANTINED)
 *   warn  → amber background (ENUM_DETECTED, TARPIT_ACTIVE, TARPIT_SATURATED)
 *   info  → slate background (everything else, including HONEYTOKEN_ISSUED)
 * Different shades ensure readability at 1366×768.
 */
import React, { useState, useMemo } from 'react';
import { useEvents } from '../hooks';
import { Card, Label } from './ui';

// ── Severity row backgrounds ──────────────────────────────────────────────────
// Three clearly distinct levels; text colors ensure ≥ 4.5:1 contrast.
const SEV_STYLE = {
  high: { background: '#3b0a0a', color: '#fca5a5', borderLeft: '3px solid #dc2626' },
  warn: { background: '#2d1b00', color: '#fcd34d', borderLeft: '3px solid #d97706' },
  info: { background: '#0c1a2e', color: '#93c5fd', borderLeft: '3px solid #1d4ed8' },
};

// Override severity for specific types that the gateway always tags "info" but
// are operationally high-priority for the dashboard viewer.
const TYPE_SEVERITY_OVERRIDE = {
  CANARY_HIT:        'high',
  HONEYTOKEN_REUSED: 'high',
  QUARANTINED:       'high',
  ENUM_DETECTED:     'warn',
  TARPIT_ACTIVE:     'warn',
  TARPIT_SATURATED:  'warn',
};

// Badge accent colors (small colored chip inside each row)
const TYPE_BADGE_COLOR = {
  CANARY_HIT:          '#dc2626',
  ENUM_DETECTED:       '#ea580c',
  TARPIT_ACTIVE:       '#2563eb',
  TARPIT_SATURATED:    '#7c3aed',
  QUARANTINED:         '#ca8a04',
  QUARANTINE_RELEASED: '#16a34a',
  HONEYTOKEN_ISSUED:   '#0891b2',
  HONEYTOKEN_REUSED:   '#db2777',
  SYSTEM_START:        '#475569',
  SIM_STARTED:         '#0d9488',
  SIM_FINISHED:        '#0d9488',
};

// Filter chips — "ISSUED" is OFF by default to reduce noise.
// The active filter set is a Set<string>; empty = show all except ISSUED.
const ALL_FILTER_TYPES = [
  'CANARY_HIT', 'ENUM_DETECTED', 'QUARANTINED',
  'HONEYTOKEN_REUSED', 'TARPIT_ACTIVE', 'TARPIT_SATURATED',
  'HONEYTOKEN_ISSUED',
];
const DEFAULT_HIDDEN = new Set(['HONEYTOKEN_ISSUED']);

// ── Aggregation helpers ───────────────────────────────────────────────────────

/**
 * Collapse consecutive HONEYTOKEN_ISSUED events by the same identity within
 * the same minute into a single synthetic "aggregated" row.
 * All other event types pass through unchanged.
 */
function aggregateIssuedEvents(events) {
  const out = [];
  // bucket key → { count, firstEvent }
  const buckets = new Map();

  for (const ev of events) {
    if (ev.event_type !== 'HONEYTOKEN_ISSUED') {
      out.push({ ...ev, _aggregated: false, _count: 1 });
      continue;
    }
    // Bucket = identity + minute truncation of timestamp
    const minute = ev.ts ? ev.ts.slice(0, 16) : '?';  // "2026-11-07T10:03"
    const key = `${ev.identity}||${minute}`;
    if (buckets.has(key)) {
      buckets.get(key).count += 1;
    } else {
      buckets.set(key, { count: 1, firstEvent: ev });
    }
  }

  // Inject aggregated ISSUED rows in timestamp order
  for (const [, { count, firstEvent }] of buckets) {
    out.push({ ...firstEvent, _aggregated: true, _count: count });
  }

  // Re-sort by ts descending (same order the API returns)
  out.sort((a, b) => (b.ts > a.ts ? 1 : b.ts < a.ts ? -1 : 0));
  return out;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function EventTimeline() {
  // hiddenTypes: set of event_type strings NOT shown
  const [hiddenTypes, setHiddenTypes] = useState(DEFAULT_HIDDEN);

  // Always fetch ALL event types from the API; we filter client-side.
  // This avoids a separate fetch when the user toggles ISSUED on/off.
  const { data, error, loading } = useEvents({ limit: 200 });

  const rawEvents = data?.data ?? [];

  // Aggregate ISSUED, then apply hidden-type filter
  const displayEvents = useMemo(() => {
    const aggregated = aggregateIssuedEvents(rawEvents);
    return aggregated.filter(ev => !hiddenTypes.has(ev.event_type));
  }, [rawEvents, hiddenTypes]);

  function toggleType(type) {
    setHiddenTypes(prev => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }

  return (
    <Card>
      <div style={styles.header}>
        <h2 style={styles.heading}>Linimasa Event</h2>
        <span style={styles.liveIndicator}>● LIVE</span>
      </div>

      {/* Filter chips — active = visible (not hidden) */}
      <div style={styles.filters}>
        {ALL_FILTER_TYPES.map(t => {
          const isVisible = !hiddenTypes.has(t);
          const badgeColor = TYPE_BADGE_COLOR[t] || '#475569';
          return (
            <button
              key={t}
              onClick={() => toggleType(t)}
              title={t === 'HONEYTOKEN_ISSUED'
                ? 'Disembunyikan secara default — klik untuk tampilkan (dikelompokkan per menit)'
                : undefined}
              style={{
                ...styles.filterBtn,
                ...(isVisible ? { borderColor: badgeColor, color: badgeColor } : styles.filterBtnOff),
              }}
            >
              {t === 'HONEYTOKEN_ISSUED' ? 'ISSUED ⤵' : t.replace(/_/g, '\u00A0')}
            </button>
          );
        })}
      </div>

      {loading && rawEvents.length === 0 && <Label>Memuat event…</Label>}
      {error && <Label style={{ color: '#f87171' }}>Event tidak tersedia: {error}</Label>}

      <div style={styles.list}>
        {displayEvents.length === 0 && !loading && (
          <Label style={{ padding: '20px 0', textAlign: 'center' }}>Belum ada event</Label>
        )}
        {displayEvents.map((ev, idx) => (
          <EventRow key={ev._aggregated ? `agg-${ev.identity}-${ev.ts}` : ev.id} event={ev} />
        ))}
      </div>

      {/* Legend */}
      <div style={styles.legend}>
        {[['high','#3b0a0a','#fca5a5','Tinggi'], ['warn','#2d1b00','#fcd34d','Sedang'], ['info','#0c1a2e','#93c5fd','Info']].map(([sev, bg, fg, label]) => (
          <span key={sev} style={{ ...styles.legendItem, background: bg, color: fg }}>
            {label}
          </span>
        ))}
        <span style={styles.legendNote}>Warna = tingkat keparahan</span>
      </div>
    </Card>
  );
}

function EventRow({ event }) {
  const sevKey   = TYPE_SEVERITY_OVERRIDE[event.event_type] || event.severity || 'info';
  const sevStyle = SEV_STYLE[sevKey] || SEV_STYLE.info;
  const badgeColor = TYPE_BADGE_COLOR[event.event_type] || '#475569';
  const ts = event.ts ? new Date(event.ts).toLocaleTimeString() : '—';
  const isAgg = event._aggregated && event._count > 1;

  return (
    <div style={{ ...styles.row, ...sevStyle }}>
      <div style={styles.rowTop}>
        <div style={styles.rowTopLeft}>
          <span
            style={{
              ...styles.typeBadge,
              background: badgeColor + '33',
              color: badgeColor,
              border: `1px solid ${badgeColor}66`,
            }}
          >
            {event.event_type}
          </span>
          {isAgg && (
            <span style={styles.aggBadge} title="Dikelompokkan — beberapa event HONEYTOKEN_ISSUED digabung">
              ×{event._count}
            </span>
          )}
        </div>
        <span style={styles.ts}>{ts}</span>
      </div>
      <div style={styles.rowBot}>
        {isAgg ? (
          <span style={styles.field}>
            {event._count} token diterbitkan → {event.identity?.slice(0, 24)}
          </span>
        ) : (
          <>
            <span style={styles.field}>{event.method} {event.path}</span>
            <span style={styles.identity} title={event.identity}>
              {event.identity?.slice(0, 24)}
            </span>
          </>
        )}
      </div>
    </div>
  );
}

const styles = {
  header:       { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 },
  heading:      { margin: 0, fontSize: 14, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 1 },
  liveIndicator:{ fontSize: 11, color: '#4ade80', fontWeight: 700, letterSpacing: 1, animation: 'pulse 2s infinite' },
  filters:      { display: 'flex', flexWrap: 'wrap', gap: 5, marginBottom: 10 },
  filterBtn:    { background: 'transparent', border: '1px solid #334155', borderRadius: 5, color: '#94a3b8', padding: '3px 9px', fontSize: 10, cursor: 'pointer', fontWeight: 600, letterSpacing: 0.3 },
  filterBtnOff: { background: 'transparent', borderColor: '#1e293b', color: '#334155' },
  list:         { display: 'flex', flexDirection: 'column', gap: 3, maxHeight: 460, overflowY: 'auto' },
  row:          { borderRadius: 5, padding: '7px 10px' },
  rowTop:       { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 3 },
  rowTopLeft:   { display: 'flex', alignItems: 'center', gap: 6 },
  typeBadge:    { fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 4, letterSpacing: 0.4 },
  aggBadge:     { fontSize: 10, fontWeight: 700, background: '#0891b233', color: '#22d3ee', border: '1px solid #0891b266', borderRadius: 10, padding: '1px 7px' },
  ts:           { fontSize: 10, color: '#475569' },
  rowBot:       { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  field:        { fontSize: 11, color: '#cbd5e1', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '70%' },
  identity:     { fontSize: 10, color: '#475569', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  legend:       { display: 'flex', alignItems: 'center', gap: 6, marginTop: 8, flexWrap: 'wrap' },
  legendItem:   { fontSize: 10, fontWeight: 600, padding: '2px 8px', borderRadius: 4 },
  legendNote:   { fontSize: 10, color: '#475569', marginLeft: 4 },
};
