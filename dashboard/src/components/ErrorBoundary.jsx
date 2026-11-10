/**
 * dashboard/src/components/ErrorBoundary.jsx
 * React error boundary — catches render errors in child components and
 * shows a fallback "panel unavailable" message instead of blanking the page.
 */
import React from 'react';

export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught:', error.message, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          background: '#0f172a', border: '1px solid #7f1d1d', borderRadius: 12,
          padding: '20px', color: '#fca5a5', fontSize: 13,
        }}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>⚠️ Panel unavailable</div>
          <div style={{ fontSize: 11, color: '#94a3b8' }}>
            {this.state.error?.message || 'Unknown error'}
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
