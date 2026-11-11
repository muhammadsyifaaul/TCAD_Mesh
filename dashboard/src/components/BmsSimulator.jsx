/**
 * dashboard/src/components/BmsSimulator.jsx
 *
 * Illustrative "BMS Simulator" page — split-screen Commander vs Adversary,
 * both going through the SAME real gateway pipeline.
 *
 * Key invariants:
 *   - Every gateway request carries X-Device-ID explicitly.
 *   - The event list shows ONLY events from the current run (scoped by runId).
 *   - "Notice" messages (success/status info) are styled amber — NOT red "Error:".
 *   - Honeypot data persists on the adversary panel across steps 2, 3, 4.
 *   - DATA PALSU label appears only while the adversary is quarantined (steps 2-4).
 *   - Step 4 shows the adversary's quarantine entry with its remaining TTL.
 *
 * Steps:
 *   0. Operasi Normal — Commander gets real shipments + routes
 *   1. Pengintaian & Tarpit — Adversary scans 404s → ENUM_DETECTED
 *   2. Canary & Penyesatan — Adversary hits /admin → honeypot data (DIFFERENT from commander)
 *   3. Honeytoken Dipakai Ulang — Second identity reuses token → HONEYTOKEN_REUSED
 *   4. Operator Mengarantina — Show TTL countdown; adversary still sees honeypot
 *   5. Pelepasan Karantina (Optional) — Release → adversary gets real data
 */
import React, { useState, useCallback, useRef } from 'react';
import { ErrorBoundary } from './ErrorBoundary';
import { Card, Label } from './ui';

// ── Step definitions ──────────────────────────────────────────────────────────

const STEPS = [
  {
    id: 0,
    title: 'Operasi Normal',
    caption: 'Komandan mengakses API logistik melalui gateway. Data asli tampil — posisi, rute, dan manifest konvoi.',
  },
  {
    id: 1,
    title: 'Pengintaian & Tarpit',
    caption: 'Adversary memindai path yang tidak ada. Gateway mendeteksi enumerasi → ENUM_DETECTED, tarpit aktif.',
  },
  {
    id: 2,
    title: 'Canary & Penyesatan',
    caption: 'Adversary mengakses /admin → canary hit. Dikarantina & dialihkan ke honeypot. Data PALSU tampil.',
  },
  {
    id: 3,
    title: 'Honeytoken Dipakai Ulang',
    caption: 'Identitas baru memakai token dari honeypot → HONEYTOKEN_REUSED terdeteksi. Atribusi sesi benar.',
  },
  {
    id: 4,
    title: 'Operator Mengarantina',
    caption: 'Operator melihat adversary di karantina dengan TTL aktif. Adversary masih mendapat data honeypot.',
  },
  {
    id: 5,
    title: 'Pelepasan Karantina',
    caption: 'Operator melepas karantina. Adversary mendapat data asli kembali — sistem kembali normal.',
  },
];

// ── fetchJSON helper ──────────────────────────────────────────────────────────

async function fetchJSON(url, opts = {}) {
  const res = await fetch(url, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...opts.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── SVG Map ───────────────────────────────────────────────────────────────────

function MiniMap({ side, shipments, isHoneypot }) {
  const accent = side === 'commander' ? '#22c55e' : '#ef4444';
  const label  = side === 'commander' ? 'Komandan' : 'Musuh';

  return (
    <svg viewBox="0 0 400 200" style={styles.map} role="img" aria-label={`Peta ${label}`}>
      {/* Grid */}
      {[40, 80, 120, 160, 200, 240, 280, 320, 360].map(x => (
        <line key={`v${x}`} x1={x} y1={0} x2={x} y2={200} stroke="#1e293b" strokeWidth={0.5} />
      ))}
      {[40, 80, 120, 160].map(y => (
        <line key={`h${y}`} x1={0} y1={y} x2={400} y2={y} stroke="#1e293b" strokeWidth={0.5} />
      ))}
      {/* River */}
      <path d="M0,120 Q100,110 200,125 T400,115" fill="none" stroke="#1e3a5f" strokeWidth={3} opacity={0.6} />
      <text x="180" y="105" fill="#3b5f7f" fontSize={9}>Sungai</text>
      {/* Roads */}
      <line x1="20" y1="40" x2="380" y2="40" stroke="#334155" strokeWidth={2} strokeDasharray="4 2" />
      <line x1="60" y1="0"  x2="60"  y2={200} stroke="#334155" strokeWidth={2} strokeDasharray="4 2" />
      {/* Depot */}
      <rect x="30" y="30" width="16" height="16" fill={accent} opacity={0.8} rx={2} />
      <text x="50" y="42" fill="#94a3b8" fontSize={8}>Depot</text>
      {/* Checkpoints */}
      {[{x:150,y:40,name:'Pos-1'},{x:280,y:40,name:'Pos-2'},{x:350,y:160,name:'Pos-3'}].map(cp => (
        <g key={cp.name}>
          <circle cx={cp.x} cy={cp.y} r={5} fill={accent} opacity={0.5} />
          <text x={cp.x+8} y={cp.y+3} fill="#64748b" fontSize={7}>{cp.name}</text>
        </g>
      ))}
      {/* Convoy blips from real data */}
      {(shipments || []).slice(0, 3).map((s, i) => {
        const x = 80 + i * 100;
        const y = isHoneypot ? 160 : 40 + (i % 2) * 10;
        return (
          <g key={s.id || i}>
            <circle cx={x} cy={y} r={5} fill={isHoneypot ? '#ef4444' : accent} opacity={0.9} />
            <text x={x+7} y={y+3} fill="#94a3b8" fontSize={6}>
              {(s.origin || '?').slice(0, 8)}
            </text>
          </g>
        );
      })}
      {/* Label */}
      <text x="10" y="15" fill={accent} fontSize={9} fontWeight="bold">
        {isHoneypot ? '⚠ DATA PALSU (Honeypot)' : 'Unit Alfa — Konvoi Logistik-01'}
      </text>
      <text x="265" y="195" fill="#334155" fontSize={7}>Ilustrasi — bukan koordinat nyata</text>
    </svg>
  );
}

// ── Commander Panel ───────────────────────────────────────────────────────────

function CommanderPanel({ data, loading, error }) {
  return (
    <Card style={{ ...styles.panel, borderColor: '#22c55e44' }}>
      <div style={styles.panelHeader}>
        <h3 style={{ ...styles.panelTitle, color: '#22c55e' }}>Pandangan Komandan</h3>
        <span style={styles.panelBadge}>🟢 LEGIT · cmd-tablet-01</span>
      </div>

      <MiniMap side="commander" shipments={data?.shipments} isHoneypot={false} />

      {loading && <Label style={styles.loadingText}>Mengambil data…</Label>}
      {error   && <div data-testid="cmd-error"   style={styles.errorMsg}>Error: {error}</div>}

      {data?.shipments && data.shipments.length > 0 && (
        <div style={styles.dataList}>
          <Label style={styles.dataHeader}>Data Pengiriman Asli:</Label>
          {data.shipments.slice(0, 3).map(s => (
            <div key={s.id} data-testid={`cmd-ship-${s.id}`} style={styles.dataRow}>
              <code style={styles.code}>{s.id}</code>
              <span style={styles.dataField}>{s.origin} → {s.destination}</span>
              <span style={styles.dataStatus}>{s.status}</span>
            </div>
          ))}
        </div>
      )}

      {data?.routes && data.routes.length > 0 && (
        <div style={styles.dataList}>
          <Label style={styles.dataHeader}>Rute:</Label>
          {data.routes.slice(0, 2).map(r => (
            <div key={r.id} style={styles.dataRow}>
              <span style={styles.dataField}>
                {r.stops?.map(st => st.location).join(' → ') || 'N/A'}
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ── Adversary Panel ───────────────────────────────────────────────────────────

function AdversaryPanel({ data, loading, error, notice, isHoneypot, quarantine, events }) {
  return (
    <Card style={{ ...styles.panel, borderColor: '#ef444444' }}>
      <div style={styles.panelHeader}>
        <h3 style={{ ...styles.panelTitle, color: '#ef4444' }}>Pandangan Musuh</h3>
        <span style={styles.panelBadge}>🔴 ADVERSARY</span>
      </div>

      {/* SVG map — always shows honeypot blips when isHoneypot */}
      <MiniMap side="adversary" shipments={data?.shipments} isHoneypot={isHoneypot} />

      {loading && <Label style={styles.loadingText}>Mengakses gateway…</Label>}

      {/* Real error (red) — only for actual failures */}
      {error && <div data-testid="adv-error" style={styles.errorMsg}>Error: {error}</div>}

      {/* Notice (amber) — for success/status information */}
      {notice && (
        <div data-testid="adv-notice" style={styles.noticeMsg}>
          {notice}
        </div>
      )}

      {/* Honeypot or real shipment data */}
      {data?.shipments && data.shipments.length > 0 && (
        <div style={styles.dataList}>
          <Label style={styles.dataHeader}>
            {isHoneypot ? '⚠ Data Honeypot (PALSU):' : 'Data Diterima (Asli):'}
          </Label>
          {data.shipments.slice(0, 3).map(s => (
            <div key={s.id} data-testid={`adv-ship-${s.id}`} style={styles.dataRow}>
              <code style={styles.code}>{s.id}</code>
              <span style={styles.dataField}>{s.origin} → {s.destination}</span>
              <span style={styles.dataStatus}>{s.status}</span>
            </div>
          ))}
        </div>
      )}

      {/* Quarantine entry — shown in step 4 */}
      {quarantine && (
        <div data-testid="adv-quarantine" style={styles.quarantineBox}>
          <div style={styles.quarantineTitle}>🔒 Karantina Aktif</div>
          <div style={styles.quarantineRow}>
            <span style={styles.quarantineLabel}>Identitas:</span>
            <code style={styles.quarantineVal}>{quarantine.identity}</code>
          </div>
          <div style={styles.quarantineRow}>
            <span style={styles.quarantineLabel}>Alasan:</span>
            <span style={styles.quarantineVal}>{quarantine.reason}</span>
          </div>
          <div style={styles.quarantineRow}>
            <span style={styles.quarantineLabel}>Berakhir dalam:</span>
            <span style={{ ...styles.quarantineVal, color: '#f87171' }}>
              {Math.floor(quarantine.remaining_ttl_sec / 60)}m {quarantine.remaining_ttl_sec % 60}s
            </span>
          </div>
        </div>
      )}

      {/* Event list — scoped to the current run's identities */}
      {events && events.length > 0 && (
        <div style={styles.eventList}>
          <Label style={styles.dataHeader}>Event Run Ini:</Label>
          {events.slice(0, 5).map((ev, i) => (
            <div key={ev.id || i} data-testid={`adv-event-${ev.event_type}`} style={styles.eventRow}>
              <span style={styles.eventBadge(ev.severity)}>{ev.event_type}</span>
              <span style={styles.eventIdentity}>{ev.identity?.slice(0, 24)}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ── Batasan Box ───────────────────────────────────────────────────────────────

function BatasanBox() {
  return (
    <div style={styles.batasanBox} role="note" aria-label="Batasan">
      <strong style={styles.batasanTitle}>Batasan:</strong>
      <ul style={styles.batasanList}>
        <li>Dalam Mode 1, penyerang dengan kredensial valid pada rute nyata TIDAK terdeteksi.</li>
        <li>TCAD Mesh tidak mengenkripsi perintah — itu tugas mTLS.</li>
        <li>Data yang ditampilkan adalah fiktif (logistik mock), bukan data operasional nyata.</li>
      </ul>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export function BmsSimulator() {
  const [step,      setStep]      = useState(0);
  const [playing,   setPlaying]   = useState(false);
  const [commander, setCommander] = useState({ data: null, loading: false, error: null });
  // Adversary state: data (shipments+routes), loading, error (real failure), notice (info/success),
  // isHoneypot (DATA PALSU label + map blips), quarantine (TTL entry for step 4)
  const [adversary, setAdversary] = useState({
    data: null, loading: false, error: null, notice: null, isHoneypot: false, quarantine: null,
  });
  // events scoped to the current run — keyed on runId so stale events are discarded
  const [events,     setEvents]     = useState([]);
  const [runId,      setRunId]      = useState(null);  // e.g. "bms-1734567890"
  const [advId,      setAdvId]      = useState('');
  const [capturedToken, setCapturedToken] = useState(null);
  const [runStartTs,  setRunStartTs]  = useState(null);  // ISO timestamp for since= param
  const [busy,       setBusy]       = useState(false);
  const playingRef = useRef(false);
  const cmdFirstIdRef = useRef(null);  // commander's first shipment ID — for step 6 comparison

  // Same-origin /gw/ proxy through dashboard nginx → gateway:8080 (avoids CORS)
  const gw   = '/gw';
  const ctrl = '';

  // ── fetch helpers ─────────────────────────────────────────────────────────

  async function gwFetch(path, deviceId, opts = {}) {
    // Every gateway request MUST carry X-Device-ID so the gateway can track identity.
    const res = await fetch(`${gw}${path}`, {
      ...opts,
      headers: { 'X-Device-ID': deviceId, ...opts.headers },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  // Fetch events scoped to a specific set of identities AND a start timestamp.
  // Uses since=<ISO> to limit the server-side query window to the current run,
  // then filters client-side by identity. This handles >100 unrelated events
  // from previous runs without missing the current run's events.
  async function fetchRunEvents(ids, since) {
    try {
      const params = new URLSearchParams({ limit: '200' });
      if (since) params.set('since', since);
      const data = await fetchJSON(`${ctrl}/events?${params}`);
      const idSet = new Set(ids.filter(Boolean));
      return (data.data || []).filter(ev => idSet.has(ev.identity));
    } catch (_) {
      return [];
    }
  }

  // Bounded-wait helper: polls a condition function at a given interval until
  // it returns true or the timeout is reached. Returns the final value.
  async function boundedWait(label, conditionFn, intervalMs, timeoutMs) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const result = await conditionFn();
      if (result) return result;
      await new Promise(r => setTimeout(r, intervalMs));
    }
    console.warn(`[BMS] Bounded wait timeout: ${label} (${timeoutMs}ms)`);
    return null;
  }

  // ── Reset ─────────────────────────────────────────────────────────────────

  async function doReset() {
    setBusy(true);
    playingRef.current = false;
    setPlaying(false);
    try {
      await fetchJSON(`${ctrl}/reset`, { method: 'POST' });
    } catch (_) { /* best-effort */ }
    setStep(0);
    setCommander({ data: null, loading: false, error: null });
    setAdversary({ data: null, loading: false, error: null, notice: null, isHoneypot: false, quarantine: null });
    setEvents([]);
    setRunId(null);
    setAdvId('');
    setCapturedToken(null);
    setRunStartTs(null);
    cmdFirstIdRef.current = null;
    setBusy(false);
  }

  // ── Step execution ────────────────────────────────────────────────────────

  const runStep = useCallback(async (stepId, currentRunId, currentAdvId, currentCapturedToken, sinceTs) => {
    setBusy(true);
    const CMD_ID = 'cmd-tablet-01';
    let returnedToken = currentCapturedToken; // default: pass through unchanged

    try {
      if (stepId === 0) {
        // Operasi Normal — Commander gets real data
        setCommander({ data: null, loading: true, error: null });
        const [ships, routes] = await Promise.all([
          gwFetch('/api/v1/shipments', CMD_ID),
          gwFetch('/api/v1/routes',    CMD_ID),
        ]);
        setCommander({
          data: { shipments: ships.data, routes: routes.data },
          loading: false,
          error: null,
        });
        // Store commander's first shipment ID for step 6 comparison
        cmdFirstIdRef.current = ships.data?.[0]?.id ?? null;
        setAdversary({ data: null, loading: false, error: null, notice: null, isHoneypot: false, quarantine: null });
        setEvents([]);

      } else if (stepId === 1) {
        // Pengintaian & Tarpit — Adversary scans 404s
        // Create a new advId for this run
        const aid = `adv-${currentRunId}`;
        setAdvId(aid);
        setAdversary({ data: null, loading: true, error: null, notice: null, isHoneypot: false, quarantine: null });

        for (let i = 0; i < 7; i++) {
          try {
            await fetch(`${gw}/nonexistent-bms-${i}`, {
              headers: { 'X-Device-ID': aid },
            });
          } catch (_) { /* expected 404 */ }
        }

        await new Promise(r => setTimeout(r, 2000));
        const evts = await fetchRunEvents([aid, CMD_ID], sinceTs);
        setEvents(evts);
        setAdversary({
          data: null, loading: false,
          error: null,
          notice: 'Tarpit aktif — 7 permintaan ke path tidak dikenal. Gateway mendeteksi enumerasi.',
          isHoneypot: false,
          quarantine: null,
        });

      } else if (stepId === 2) {
        // Canary & Penyesatan — Adversary hits /admin
        const aid = currentAdvId;
        setAdversary(prev => ({ ...prev, loading: true, error: null, notice: null }));

        // Canary hit — X-Device-ID is the adversary identity
        await fetch(`${gw}/admin`, { headers: { 'X-Device-ID': aid } }).catch(() => {});
        await new Promise(r => setTimeout(r, 600));

        // Adversary is now quarantined → gateway routes to honeypot
        const hpShips = await gwFetch('/api/v1/shipments', aid);
        const hpRoutes = await gwFetch('/api/v1/routes',   aid);

        // Capture the first honeypot token for step 3 — return it to caller
        const token = hpShips.data?.[0]?.id ?? null;
        setCapturedToken(token);
        returnedToken = token;

        await new Promise(r => setTimeout(r, 800));
        const evts = await fetchRunEvents([aid, CMD_ID], sinceTs);
        setEvents(evts);
        setAdversary({
          data: { shipments: hpShips.data, routes: hpRoutes.data },
          loading: false,
          error: null,
          notice: null,
          isHoneypot: true,
          quarantine: null,
        });

      } else if (stepId === 3) {
        // Honeytoken Dipakai Ulang — new identity reuses captured token
        // Keep the honeypot data from step 2 visible — just update notice + loading
        setAdversary(prev => ({ ...prev, loading: true, notice: null, error: null }));

        const token = currentCapturedToken;
        // Wait for gateway honeytoken poller to pick up the new token (500ms default)
        await new Promise(r => setTimeout(r, 1500));

        const reuserId = `adv-reuse-${currentRunId}`;
        // Embed token in ?doc= query param — gateway scans URI for registered honeytokens
        await fetch(`${gw}/api/v1/shipments?doc=${token}`, {
          headers: { 'X-Device-ID': reuserId },
        }).catch(() => {});

        // ── BOUNDED WAIT: poll for HONEYTOKEN_REUSED event from this run ──────
        // Step 4 (UI step 4) must NOT claim detection until HONEYTOKEN_REUSED
        // is visible in the event list. Poll every 500ms, up to 10s.
        const reuseFound = await boundedWait(
          'HONEYTOKEN_REUSED event',
          async () => {
            const evts = await fetchRunEvents([currentAdvId, reuserId, CMD_ID], sinceTs);
            return evts.some(ev => ev.event_type === 'HONEYTOKEN_REUSED') ? evts : null;
          },
          500, 10000,
        );

        const evts = reuseFound || await fetchRunEvents([currentAdvId, reuserId, CMD_ID], sinceTs);
        setEvents(evts);

        // Keep honeypot DATA from step 2 visible — only update notice (amber, not error)
        setAdversary(prev => ({
          ...prev,
          loading: false,
          error: null,
          notice: reuseFound
            ? `✅ HONEYTOKEN_REUSED terdeteksi! Token ${token} dipakai ulang oleh ${reuserId}`
            : `Menunggu HONEYTOKEN_REUSED... (timeout — periksa event timeline)`,
          isHoneypot: true,   // keep DATA PALSU label
          quarantine: null,
        }));

      } else if (stepId === 4) {
        // Operator Mengarantina — show TTL, adversary still in honeypot
        const aid = currentAdvId;
        setAdversary(prev => ({ ...prev, loading: true, error: null, notice: null }));

        // ── BOUNDED WAIT: poll for the adversary's quarantine entry ────────────
        // Step 5 (UI step 5) must NOT advance until the quarantine entry is visible.
        // Poll every 500ms, up to 10s.
        const qEntry = await boundedWait(
          `quarantine entry for ${aid}`,
          async () => {
            try {
              const qData = await fetchJSON(`${ctrl}/quarantine`);
              return (qData.data || []).find(q => q.identity === aid) ?? null;
            } catch (_) { return null; }
          },
          500, 10000,
        );

        const evts = await fetchRunEvents([aid, `adv-reuse-${currentRunId}`, CMD_ID], sinceTs);
        setEvents(evts);

        // Keep honeypot data, add quarantine info box
        setAdversary(prev => ({
          ...prev,
          loading: false,
          error: null,
          notice: qEntry ? null : 'Karantina tidak ditemukan setelah 10 detik.',
          isHoneypot: true,   // still in honeypot
          quarantine: qEntry, // shows TTL countdown box
        }));

      } else if (stepId === 5) {
        // Pelepasan Karantina — release, adversary gets real data
        const aid = currentAdvId;
        setAdversary(prev => ({ ...prev, loading: true, error: null, notice: null }));

        try {
          await fetchJSON(`${ctrl}/quarantine/${aid}/release`, { method: 'POST' });
        } catch (_) { /* best-effort */ }

        // ── BOUNDED WAIT: poll until adversary data equals commander data ──────
        // Step 6 (UI step 6) must NOT complete until the refetched adversary data
        // equals the commander data (same first shipment ID) AND DATA PALSU is gone.
        // Poll every 500ms, up to 15s (quarantine poller is 2s + release propagation).
        const expectedId = cmdFirstIdRef.current;
        const realData = await boundedWait(
          `adversary data == commander (${expectedId})`,
          async () => {
            try {
              const ships = await gwFetch('/api/v1/shipments', aid);
              const firstId = ships.data?.[0]?.id ?? null;
              if (firstId && firstId === expectedId) {
                return ships;
              }
              return null;
            } catch (_) { return null; }
          },
          500, 15000,
        );

        const finalShips = realData || await gwFetch('/api/v1/shipments', aid);
        const evts = await fetchRunEvents([aid, `adv-reuse-${currentRunId}`, CMD_ID], sinceTs);
        setEvents(evts);

        const firstIdMatches = finalShips.data?.[0]?.id === expectedId;
        setAdversary({
          data: { shipments: finalShips.data, routes: [] },
          loading: false,
          error: null,
          notice: firstIdMatches
            ? '✅ Karantina dilepas. Adversary mendapat data asli kembali.'
            : 'Karantina dilepas, tetapi data belum cocok. Periksa timeline.',
          isHoneypot: false,   // remove DATA PALSU label
          quarantine: null,    // remove TTL box
        });
      }
    } catch (e) {
      setAdversary(prev => ({ ...prev, loading: false, error: e.message }));
    } finally {
      setBusy(false);
    }
    return returnedToken;
  }, []);

  // ── Controls ─────────────────────────────────────────────────────────────

  async function handlePlay() {
    // Rerun safety: reset first if already finished
    if (step >= STEPS.length - 1) {
      await doReset();
    }
    const rid = `run-${Date.now()}`;
    setRunId(rid);
    // Record run start time as ISO for since= parameter in event queries
    const ts = new Date().toISOString().replace(/\.\d+Z$/, 'Z');
    setRunStartTs(ts);
    setPlaying(true);
    playingRef.current = true;

    const aid = `adv-${rid}`;
    setAdvId(aid);  // set once — used for all subsequent steps

    let currentToken = null;  // captured in step 2, used in step 3

    for (let s = 0; s < STEPS.length; s++) {
      if (!playingRef.current && s > 0) break;
      setStep(s);

      // runStep needs: (stepId, runId, advId, capturedToken, sinceTs)
      const returned = await runStep(s, rid, aid, currentToken, ts);

      // runStep returns the captured token when it captures one (step 2)
      if (returned !== null && returned !== undefined && returned !== currentToken) {
        currentToken = returned;
      }

      if (s < STEPS.length - 1 && playingRef.current) {
        await new Promise(r => setTimeout(r, 1200));
      }
    }
    setPlaying(false);
    playingRef.current = false;
  }

  function handlePause() {
    setPlaying(false);
    playingRef.current = false;
  }

  async function handleNext() {
    // For Next, we need to know the current run's ids
    const rid = runId || `run-${Date.now()}`;
    if (!runId) setRunId(rid);
    const aid = advId || `adv-${rid}`;
    if (!advId) setAdvId(aid);
    const ts = runStartTs || new Date().toISOString().replace(/\.\d+Z$/, 'Z');
    if (!runStartTs) setRunStartTs(ts);
    const next = Math.min(step + 1, STEPS.length - 1);
    setStep(next);
    const returned = await runStep(next, rid, aid, capturedToken, ts);
    // If step 2 returned a token, update state (runStep called setCapturedToken too)
    if (returned && returned !== capturedToken) {
      setCapturedToken(returned);
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div style={styles.root}>
      <div style={styles.banner} role="alert">
        ⚠ Simulasi ilustratif, bukan sistem BMS TNI AD.
      </div>

      <BatasanBox />

      {/* Step chips */}
      <div style={styles.stepBar}>
        {STEPS.map((s, i) => (
          <div
            key={s.id}
            style={{
              ...styles.stepChip,
              ...(i === step ? styles.stepChipActive : {}),
              ...(i < step  ? styles.stepChipDone   : {}),
            }}
          >
            <span style={styles.stepNum}>{i + 1}</span>
            <span style={styles.stepLabel}>{s.title}</span>
          </div>
        ))}
      </div>

      {/* Caption */}
      <div data-testid="step-caption" style={styles.caption}>
        <strong>Langkah {step + 1}/{STEPS.length}:</strong> {STEPS[step].caption}
      </div>

      {/* Controls */}
      <div style={styles.controls}>
        <button onClick={handlePlay}  disabled={busy || playing}
          style={{ ...styles.ctrlBtn, ...styles.ctrlPrimary }}>▶ Putar</button>
        <button onClick={handlePause} disabled={!playing}
          style={{ ...styles.ctrlBtn, ...styles.ctrlSecondary }}>⏸ Jeda</button>
        <button onClick={handleNext}  disabled={busy || step >= STEPS.length - 1}
          style={{ ...styles.ctrlBtn, ...styles.ctrlSecondary }}>⏭ Lanjut</button>
        <button onClick={doReset}     disabled={busy}
          style={{ ...styles.ctrlBtn, ...styles.ctrlDanger }}>↺ Reset</button>
      </div>

      {/* Split screen */}
      <div style={styles.split}>
        <ErrorBoundary>
          <CommanderPanel
            data={commander.data}
            loading={commander.loading}
            error={commander.error}
          />
        </ErrorBoundary>
        <ErrorBoundary>
          <AdversaryPanel
            data={adversary.data}
            loading={adversary.loading}
            error={adversary.error}
            notice={adversary.notice}
            isHoneypot={adversary.isHoneypot}
            quarantine={adversary.quarantine}
            events={events}
          />
        </ErrorBoundary>
      </div>
    </div>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const styles = {
  root: { display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 1400, width: '100%', alignSelf: 'center' },
  banner: {
    background: '#422006', border: '2px solid #a16207', borderRadius: 8,
    padding: '12px 16px', textAlign: 'center', fontSize: 16, fontWeight: 700, color: '#fde047',
  },
  batasanBox: {
    background: '#0f172a', border: '1px solid #334155', borderRadius: 8,
    padding: '12px 16px', fontSize: 13, color: '#94a3b8',
  },
  batasanTitle: { color: '#fb923c', fontSize: 14 },
  batasanList:  { margin: '6px 0 0 16px', padding: 0, lineHeight: 1.6, fontSize: 13 },
  stepBar:      { display: 'flex', gap: 4, flexWrap: 'wrap' },
  stepChip: {
    display: 'flex', alignItems: 'center', gap: 6,
    background: '#1e293b', border: '1px solid #334155', borderRadius: 6,
    padding: '8px 12px', fontSize: 12, color: '#64748b',
  },
  stepChipActive: { borderColor: '#2563eb', color: '#93c5fd', background: '#1e3a5f' },
  stepChipDone:   { borderColor: '#16a34a', color: '#4ade80', background: '#052e16' },
  stepNum:   { fontWeight: 700, fontSize: 15 },
  stepLabel: { fontSize: 11 },
  caption: {
    background: '#0f172a', border: '1px solid #1e293b', borderRadius: 6,
    padding: '12px 16px', fontSize: 14, color: '#cbd5e1', lineHeight: 1.5,
  },
  controls: { display: 'flex', gap: 8, flexWrap: 'wrap' },
  ctrlBtn: {
    border: '1px solid #334155', borderRadius: 6, padding: '10px 18px',
    fontSize: 14, fontWeight: 600, cursor: 'pointer', background: '#1e293b', color: '#cbd5e1',
  },
  ctrlPrimary:   { background: '#1e3a5f', borderColor: '#2563eb', color: '#93c5fd' },
  ctrlSecondary: { background: '#1e293b', borderColor: '#334155', color: '#94a3b8' },
  ctrlDanger:    { background: '#3b1d1d', borderColor: '#7f1d1d', color: '#fca5a5' },
  split: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 },
  panel: { border: '1px solid #1e293b', borderRadius: 12, padding: 16, background: '#0f172a', minHeight: 300 },
  panelHeader: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 },
  panelTitle:  { margin: 0, fontSize: 17, fontWeight: 700 },
  panelBadge:  { fontSize: 11, fontWeight: 700, padding: '4px 10px', borderRadius: 4 },
  map:         { width: '100%', height: 'auto', borderRadius: 8, background: '#020617', marginBottom: 10 },
  loadingText: { color: '#64748b', padding: '8px 0', fontSize: 13 },
  // errorMsg: red — real failures only
  errorMsg: {
    background: '#3b0a0a', border: '1px solid #7f1d1d', borderRadius: 6,
    color: '#fca5a5', padding: '8px 12px', fontSize: 13, marginBottom: 6,
  },
  // noticeMsg: amber — success / informational status (NOT an error)
  noticeMsg: {
    background: '#1c1400', border: '1px solid #a16207', borderRadius: 6,
    color: '#fde047', padding: '8px 12px', fontSize: 13, marginBottom: 6,
  },
  dataList:   { marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 },
  dataHeader: { fontSize: 12, color: '#64748b', marginBottom: 4 },
  dataRow: {
    display: 'flex', alignItems: 'center', gap: 8,
    background: '#1e293b', borderRadius: 4, padding: '8px 10px', fontSize: 12,
  },
  code:        { fontFamily: 'monospace', color: '#7dd3fc', fontSize: 11 },
  dataField:   { color: '#cbd5e1', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12 },
  dataStatus:  { fontSize: 10, color: '#94a3b8', padding: '2px 8px', borderRadius: 3, background: '#334155' },
  quarantineBox: {
    marginTop: 8, background: '#1a0a1a', border: '1px solid #7c3aed',
    borderRadius: 6, padding: '10px 12px',
  },
  quarantineTitle: { fontSize: 13, fontWeight: 700, color: '#c084fc', marginBottom: 6 },
  quarantineRow:   { display: 'flex', gap: 8, marginBottom: 3, fontSize: 12 },
  quarantineLabel: { color: '#64748b', minWidth: 80 },
  quarantineVal:   { color: '#e2e8f0', fontFamily: 'monospace' },
  eventList:  { marginTop: 8, display: 'flex', flexDirection: 'column', gap: 3 },
  eventRow: {
    display: 'flex', alignItems: 'center', gap: 6,
    fontSize: 11, padding: '5px 8px', borderRadius: 4, background: '#1e293b',
  },
  eventBadge: (sev) => ({
    fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 3,
    background: sev === 'high' ? '#7f1d1d' : sev === 'warn' ? '#431407' : '#1e3a5f',
    color:      sev === 'high' ? '#fca5a5' : sev === 'warn' ? '#fdba74' : '#93c5fd',
  }),
  eventIdentity: { color: '#64748b', fontFamily: 'monospace', fontSize: 10 },
};
