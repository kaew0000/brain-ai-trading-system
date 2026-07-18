// ============================================================
// Brain Bot V15 — World Overlay
// Right-side HUD panels that float above the Phaser canvas:
// Live Feed, Open Position, Confidence, Commander Terminal.
// These are pure React — zero Phaser involvement.
// ============================================================

import { useState, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useWorldStore, THEME_COLORS } from '../worldStore';
import { sendCommand } from '../worldApi';

// ── Panel wrapper ─────────────────────────────────────────────────────────────

function Panel({
  title,
  children,
  accent,
  bg,
  border,
  onClose,
  collapsed,
  onToggle,
}: {
  title: string;
  children: React.ReactNode;
  accent: string;
  bg: string;
  border: string;
  onClose?: () => void;
  collapsed?: boolean;
  onToggle?: () => void;
}) {
  return (
    <div style={{
      background: bg, border: `1px solid ${border}`,
      borderTop: `2px solid ${accent}`,
      borderRadius: 2, marginBottom: 6, overflow: 'hidden',
      boxShadow: `0 0 8px ${accent}18`,
    }}>
      <div
        style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '5px 10px', cursor: 'pointer', userSelect: 'none',
          borderBottom: `1px solid ${border}`,
        }}
        onClick={onToggle}
      >
        <span style={{ color: accent, fontSize: 9, fontFamily: 'monospace', fontWeight: 'bold', letterSpacing: 1 }}>
          {title}
        </span>
        <span style={{ display: 'flex', gap: 4 }}>
          {onClose && (
            <button
              onClick={(e) => { e.stopPropagation(); onClose(); }}
              style={{
                background: 'none', border: 'none', color: '#666', cursor: 'pointer',
                fontSize: 10, padding: '0 2px',
              }}
            >✕</button>
          )}
          <span style={{ color: '#666', fontSize: 10 }}>{collapsed ? '▼' : '▲'}</span>
        </span>
      </div>
      {!collapsed && (
        <div style={{ padding: '8px 10px' }}>{children}</div>
      )}
    </div>
  );
}

// ── Live Feed ─────────────────────────────────────────────────────────────────

function LiveFeedPanel({ colors }: { colors: typeof THEME_COLORS['dark'] }) {
  const { recentEvents, wsConnected } = useWorldStore();
  const [collapsed, setCollapsed] = useState(false);

  const levelColor: Record<string, string> = {
    info: colors.text, warn: '#ffaa00', error: '#ff4444', success: '#00ff88',
  };

  return (
    <Panel
      title="+ LIVE FEED"
      accent={colors.accent}
      bg={colors.panel}
      border={colors.border}
      collapsed={collapsed}
      onToggle={() => setCollapsed((v) => !v)}
    >
      {!wsConnected && (
        <div style={{
          color: '#ff4444', fontSize: 8, padding: '4px 0',
          fontFamily: 'monospace', marginBottom: 6,
          animation: 'pulse 1s ease-in-out infinite',
        }}>
          ⚠ DISCONNECTED
        </div>
      )}
      <div style={{ maxHeight: 110, overflowY: 'auto' }}>
        {recentEvents.length === 0 && (
          <div style={{ color: '#444', fontSize: 8, fontFamily: 'monospace' }}>
            Waiting for events…
          </div>
        )}
        {recentEvents.slice(0, 12).map((ev) => (
          <div key={ev.id} style={{
            display: 'flex', gap: 6, marginBottom: 4,
            fontSize: 8, fontFamily: 'monospace',
          }}>
            <span style={{ color: '#555', flexShrink: 0 }}>
              {new Date(ev.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </span>
            <span style={{ color: levelColor[ev.level] ?? colors.text, flex: 1 }}>
              {ev.event}
            </span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

// ── Open Position ─────────────────────────────────────────────────────────────

function OpenPositionPanel({ colors }: { colors: any }) {
  const paper = useWorldStore((s) => s.paper);
  const pos = paper?.open_position;
  const [collapsed, setCollapsed] = useState(false);

  const uPnlColor = (pos?.unrealized_pnl ?? 0) >= 0 ? '#00ff88' : '#ff4444';

  return (
    <Panel title="OPEN POSITION" accent={colors.accent} bg={colors.panel} border={colors.border}
      collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)}>
      {pos ? (
        <div style={{ fontFamily: 'monospace' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <span style={{
              color: pos.side === 'LONG' ? '#00ff88' : '#ff4444',
              fontSize: 11, fontWeight: 'bold',
            }}>
              {pos.side}
            </span>
            <span style={{ color: colors.text, fontSize: 10 }}>
              {pos.size.toFixed(4)} BTC
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
            <span style={{ color: '#666', fontSize: 8 }}>Entry</span>
            <span style={{ color: colors.text, fontSize: 8 }}>
              {pos.entry_price.toLocaleString()}
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 2 }}>
            <span style={{ color: '#666', fontSize: 8 }}>uPnL</span>
            <span style={{ color: uPnlColor, fontSize: 8, fontWeight: 'bold' }}>
              {(pos.unrealized_pnl >= 0 ? '+' : '')}{pos.unrealized_pnl.toFixed(2)} USDT
            </span>
          </div>
        </div>
      ) : (
        <div style={{ color: '#555', fontSize: 8, fontFamily: 'monospace' }}>
          No open position
        </div>
      )}
    </Panel>
  );
}

// ── Confidence Gauge ──────────────────────────────────────────────────────────

function ConfidencePanel({ colors }: { colors: any }) {
  const decision = useWorldStore((s) => s.decision);
  const [collapsed, setCollapsed] = useState(false);
  const conf = decision?.confidence ?? 0;
  const pct = Math.round(conf * 100);
  const gaugeDeg = conf * 360;
  const gaugeColor = conf > 0.7 ? '#00ff88' : conf > 0.4 ? '#ffaa00' : '#ff4444';

  return (
    <Panel title="● CONFIDENCE" accent={colors.accent} bg={colors.panel} border={colors.border}
      collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        {/* Circular gauge */}
        <div style={{
          position: 'relative', width: 52, height: 52, flexShrink: 0,
        }}>
          <svg viewBox="0 0 52 52" style={{ width: 52, height: 52, transform: 'rotate(-90deg)' }}>
            <circle cx="26" cy="26" r="22" fill="none" stroke="#1a1a2e" strokeWidth="6" />
            <circle cx="26" cy="26" r="22" fill="none" stroke={gaugeColor} strokeWidth="6"
              strokeDasharray={`${conf * 138.2} 138.2`} strokeLinecap="round" />
          </svg>
          <div style={{
            position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
            justifyContent: 'center', color: gaugeColor, fontSize: 11,
            fontWeight: 'bold', fontFamily: 'monospace',
          }}>
            {pct}%
          </div>
        </div>
        {/* Score bars */}
        <div style={{ flex: 1 }}>
          {decision?.scores
            ? Object.entries(decision.scores).slice(0, 5).map(([k, v]) => (
                <div key={k} style={{ marginBottom: 3 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 1 }}>
                    <span style={{ color: '#888', fontSize: 7, fontFamily: 'monospace' }}>{k.toUpperCase()}</span>
                    <span style={{ color: colors.accent, fontSize: 7, fontFamily: 'monospace' }}>
                      {typeof v === 'number' ? `${Math.round(v * 100)}%` : String(v)}
                    </span>
                  </div>
                  <div style={{ height: 3, background: '#111', borderRadius: 1 }}>
                    <div style={{
                      height: '100%', borderRadius: 1,
                      width: `${typeof v === 'number' ? v * 100 : 0}%`,
                      background: colors.accent,
                    }} />
                  </div>
                </div>
              ))
            : <div style={{ color: '#555', fontSize: 8, fontFamily: 'monospace' }}>No scores</div>
          }
        </div>
      </div>
    </Panel>
  );
}

// ── Commander Terminal ────────────────────────────────────────────────────────

function CommanderPanel({ colors }: { colors: any }) {
  const [input, setInput] = useState('');
  const [log, setLog] = useState<{ line: string; isCmd: boolean }[]>([
    { line: '> show positions', isCmd: true },
    { line: '> show pnl', isCmd: true },
    { line: '> pause trader', isCmd: true },
    { line: '> risk report', isCmd: true },
    { line: '> explain last decision', isCmd: true },
  ]);
  const [collapsed, setCollapsed] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  const exec = useCallback(async () => {
    const cmd = input.trim();
    if (!cmd) return;
    setInput('');
    setLog((l) => [...l, { line: `> ${cmd}`, isCmd: true }]);
    const res = await sendCommand(cmd);
    setLog((l) => [...l, {
      line: res.message ?? JSON.stringify(res),
      isCmd: false,
    }]);
    setTimeout(() => { logRef.current?.scrollTo(0, 99999); }, 50);
  }, [input]);

  return (
    <Panel title="COMMANDER TERMINAL" accent={colors.accent} bg={colors.panel} border={colors.border}
      collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)}>
      <div ref={logRef} style={{
        height: 88, overflowY: 'auto', fontFamily: 'monospace',
        fontSize: 8, marginBottom: 8, lineHeight: 1.6,
      }}>
        {log.map((l, i) => (
          <div key={i} style={{ color: l.isCmd ? colors.accent : colors.text }}>{l.line}</div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 4 }}>
        <input value={input} onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && exec()}
          placeholder="Type command…"
          style={{
            flex: 1, background: '#000', border: `1px solid ${colors.border}`,
            color: colors.text, padding: '4px 6px', fontSize: 8, borderRadius: 2,
            outline: 'none', fontFamily: 'monospace',
          }}
        />
        <button onClick={exec}
          style={{
            background: 'none', border: `1px solid ${colors.border}`,
            color: colors.accent, padding: '4px 8px', fontSize: 9,
            cursor: 'pointer', borderRadius: 2, fontFamily: 'monospace',
          }}>
          ▶
        </button>
      </div>
    </Panel>
  );
}

// ── System Health ─────────────────────────────────────────────────────────────

function HealthPanel({ colors }: { colors: any }) {
  const { systemHealth, agents, wsConnected } = useWorldStore();
  const [collapsed, setCollapsed] = useState(false);
  const statusColor = {
    ALIVE: '#00ff88', STALE: '#ffaa00', DEAD: '#ff4444', UNKNOWN: '#666',
  };

  return (
    <Panel title="HEALTH" accent={colors.accent} bg={colors.panel} border={colors.border}
      collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)}>
      <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
        <span style={{
          color: wsConnected ? '#00ff88' : '#ff4444', fontSize: 8, fontFamily: 'monospace',
        }}>
          {wsConnected ? '● LIVE' : '○ OFFLINE'}
        </span>
        <span style={{
          color: statusColor[systemHealth?.overall_status ?? 'UNKNOWN'],
          fontSize: 8, fontFamily: 'monospace',
        }}>
          SYS: {systemHealth?.overall_status ?? '…'}
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 3 }}>
        {Object.entries(agents).slice(0, 8).map(([k, v]) => (
          <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 7, fontFamily: 'monospace' }}>
            <span style={{ color: statusColor[v.status] ?? '#666' }}>●</span>
            <span style={{ color: '#888' }}>{k.slice(0, 8)}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

// ── Main Overlay ──────────────────────────────────────────────────────────────

export default function WorldOverlay() {
  const theme = useWorldStore((s) => s.theme);
  const colors = THEME_COLORS[theme];

  return (
    <div style={{
      position: 'absolute', top: 0, right: 0,
      width: 200, height: '100%', pointerEvents: 'none',
      display: 'flex', flexDirection: 'column',
      justifyContent: 'flex-start', padding: 8, gap: 0,
      overflow: 'hidden',
      zIndex: 100,
    }}>
      <div style={{ pointerEvents: 'all', overflow: 'hidden auto', flex: 1 }}>
        <LiveFeedPanel colors={colors} />
        <OpenPositionPanel colors={colors} />
        <ConfidencePanel colors={colors} />
        <CommanderPanel colors={colors} />
        <HealthPanel colors={colors} />
      </div>
    </div>
  );
}
