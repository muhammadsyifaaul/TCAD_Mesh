/**
 * Shared primitive UI components.
 */
import React from 'react';

export function Card({ children, style }) {
  return (
    <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 12, padding: '20px 20px', ...style }}>
      {children}
    </div>
  );
}

export function Metric({ children, style }) {
  return (
    <div style={{ fontSize: 28, fontWeight: 700, color: '#e2e8f0', lineHeight: 1, ...style }}>
      {children}
    </div>
  );
}

export function Label({ children, style }) {
  return (
    <div style={{ fontSize: 12, color: '#64748b', ...style }}>
      {children}
    </div>
  );
}

export function Badge({ children, color = '#475569' }) {
  return (
    <span style={{
      background: color + '22',
      color,
      border: `1px solid ${color}55`,
      borderRadius: 4,
      padding: '1px 7px',
      fontSize: 10,
      fontWeight: 700,
      letterSpacing: 0.5,
    }}>
      {children}
    </span>
  );
}
