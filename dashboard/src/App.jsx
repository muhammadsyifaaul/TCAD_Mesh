/**
 * dashboard/src/App.jsx
 * Root layout — dark-mode operator dashboard.
 * Every panel is wrapped in an ErrorBoundary so one panel's failure
 * shows "panel unavailable" instead of blanking the page.
 *
 * Simple hash-based routing: #/ or empty = main dashboard, #/bms = BMS Simulator.
 * No react-router dependency — just window.location.hash.
 */
import React, { useState, useEffect } from 'react';
import { ErrorBoundary }    from './components/ErrorBoundary';
import { StatsPanel }       from './components/StatsPanel';
import { EventTimeline }    from './components/EventTimeline';
import { QuarantineTable }  from './components/QuarantineTable';
import { HoneytokenPanel }  from './components/HoneytokenPanel';
import { SimPanel }         from './components/SimPanel';
import { BmsSimulator }     from './components/BmsSimulator';

function useHashRoute() {
  const [route, setRoute] = useState(() => {
    const h = window.location.hash.replace(/^#\/?/, '');
    return h === 'bms' ? 'bms' : 'dashboard';
  });
  useEffect(() => {
    const onHash = () => {
      const h = window.location.hash.replace(/^#\/?/, '');
      setRoute(h === 'bms' ? 'bms' : 'dashboard');
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  return route;
}

export default function App() {
  const route = useHashRoute();

  return (
    <div style={styles.root}>
      <header style={styles.header}>
        <div style={styles.logo}>
          <span style={styles.logoIcon}>🛡</span>
          <span style={styles.logoText}>TCAD Mesh</span>
          <span style={styles.logoSub}>Dasbor Operator</span>
        </div>
        <div style={styles.nav}>
          <a
            href="#/"
            style={{ ...styles.navLink, ...(route === 'dashboard' ? styles.navLinkActive : {}) }}
          >Dasbor</a>
          <a
            href="#/bms"
            style={{ ...styles.navLink, ...(route === 'bms' ? styles.navLinkActive : {}) }}
          >BMS Simulator</a>
          <span style={styles.badge}>Mode 1 · Pertahanan Aktif</span>
        </div>
      </header>

      {route === 'bms' ? (
        <main style={styles.main}>
          <ErrorBoundary>
            <BmsSimulator />
          </ErrorBoundary>
        </main>
      ) : (
        <main style={styles.main}>
          {/* Row 1: Stats + Sim Control */}
          <div style={styles.row2}>
            <ErrorBoundary>
              <StatsPanel />
            </ErrorBoundary>
            <ErrorBoundary>
              <SimPanel />
            </ErrorBoundary>
          </div>

          {/* Row 2: Event Timeline (full width) */}
          <ErrorBoundary>
            <EventTimeline />
          </ErrorBoundary>

          {/* Row 3: Quarantine + Honeytokens */}
          <div style={styles.row2}>
            <ErrorBoundary>
              <QuarantineTable />
            </ErrorBoundary>
            <ErrorBoundary>
              <HoneytokenPanel />
            </ErrorBoundary>
          </div>
        </main>
      )}

      <footer style={styles.footer}>
        TCAD Mesh v0.1.0 · Kartika Cyber Hackathon 2026 · Semua data adalah waktu nyata
      </footer>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50%      { opacity: 0.4; }
        }
        * { box-sizing: border-box; }
        body { margin: 0; background: #020617; }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #0f172a; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
      `}</style>
    </div>
  );
}

const styles = {
  root: {
    minHeight: '100vh',
    background: '#020617',
    color: '#e2e8f0',
    fontFamily: "'Inter', 'Segoe UI', system-ui, sans-serif",
    display: 'flex',
    flexDirection: 'column',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '14px 28px',
    background: '#0a0f1e',
    borderBottom: '1px solid #1e293b',
    position: 'sticky',
    top: 0,
    zIndex: 100,
  },
  logo: { display: 'flex', alignItems: 'center', gap: 10 },
  logoIcon: { fontSize: 22 },
  logoText: { fontSize: 18, fontWeight: 700, color: '#e2e8f0', letterSpacing: -0.5 },
  logoSub:  { fontSize: 12, color: '#475569', marginLeft: 4 },
  badge:    { fontSize: 11, fontWeight: 700, color: '#4ade80', background: '#14532d44', border: '1px solid #14532d', borderRadius: 20, padding: '4px 12px', letterSpacing: 0.5 },
  nav:       { display: 'flex', alignItems: 'center', gap: 12 },
  navLink:   { fontSize: 13, fontWeight: 600, color: '#64748b', textDecoration: 'none', padding: '4px 12px', borderRadius: 6, transition: 'color 0.15s' },
  navLinkActive: { color: '#93c5fd', background: '#1e3a5f' },
  main: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    gap: 16,
    padding: '20px 24px',
    maxWidth: 1400,
    width: '100%',
    alignSelf: 'center',
  },
  row2: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))',
    gap: 16,
  },
  footer: {
    textAlign: 'center',
    fontSize: 11,
    color: '#334155',
    padding: '12px 24px',
    borderTop: '1px solid #1e293b',
  },
};
