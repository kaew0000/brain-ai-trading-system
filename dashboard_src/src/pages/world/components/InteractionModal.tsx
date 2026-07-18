// ============================================================
// Brain Bot V15 — Interaction Modal
// Room-specific modal overlays. Each modal fetches live data
// from the backend and presents it in 8-bit style.
// ============================================================

import { useEffect, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useWorldStore, THEME_COLORS } from '../worldStore';
import { fetchRoomData, sendCommand, chatWithAgent } from '../worldApi';
import { ROOM_DEFINITIONS } from '../Room';
import type { ModalType } from '../types/world.types';

// ── Shared styles ─────────────────────────────────────────────────────────────

const pixel = { fontFamily: 'monospace', imageRendering: 'pixelated' as const };

// ── Sub-modals ────────────────────────────────────────────────────────────────

function CeoModal({ theme }: { theme: any }) {
  const { decision, agents } = useWorldStore();
  const [chatInput, setChatInput] = useState('');
  const [chatHistory, setChatHistory] = useState<{ q: string; a: string }[]>([]);
  const [loading, setLoading] = useState(false);

  const conf = decision?.confidence ?? 0;
  const confPct = Math.round(conf * 100);
  const signal = decision?.signal ?? '…';

  const signalColor = signal === 'LONG' ? '#00ff88' : signal === 'SHORT' ? '#ff4444' : '#ffaa00';

  const sendChat = useCallback(async () => {
    if (!chatInput.trim()) return;
    const q = chatInput;
    setChatInput('');
    setLoading(true);
    const res = await chatWithAgent('ceo', q);
    setChatHistory((h) => [...h, { q, a: res.answer ?? '(no response)' }]);
    setLoading(false);
  }, [chatInput]);

  return (
    <div style={{ ...pixel }}>
      <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
        {/* Signal */}
        <div style={{ flex: 1, border: `1px solid ${signalColor}`, padding: 12, borderRadius: 2 }}>
          <div style={{ color: '#888', fontSize: 9, marginBottom: 4 }}>CURRENT SIGNAL</div>
          <div style={{ color: signalColor, fontSize: 22, fontWeight: 'bold' }}>{signal}</div>
        </div>
        {/* Confidence */}
        <div style={{ flex: 1, border: `1px solid ${theme.border}`, padding: 12, borderRadius: 2 }}>
          <div style={{ color: '#888', fontSize: 9, marginBottom: 6 }}>CONFIDENCE</div>
          <div style={{ position: 'relative', height: 8, background: '#111', borderRadius: 2 }}>
            <div style={{
              position: 'absolute', left: 0, top: 0, height: '100%',
              width: `${confPct}%`,
              background: conf > 0.7 ? '#00ff88' : conf > 0.4 ? '#ffaa00' : '#ff4444',
              borderRadius: 2, transition: 'width 0.5s ease',
            }} />
          </div>
          <div style={{ color: theme.text, fontSize: 16, marginTop: 4 }}>{confPct}%</div>
        </div>
      </div>

      {/* Reasoning */}
      {decision?.reasoning && (
        <div style={{
          background: '#000', border: `1px solid ${theme.border}`,
          borderRadius: 2, padding: 10, marginBottom: 12,
          maxHeight: 80, overflowY: 'auto', fontSize: 9, color: '#aaa', lineHeight: 1.6,
        }}>
          {decision.reasoning}
        </div>
      )}

      {/* Scores breakdown */}
      {decision?.scores && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
          {Object.entries(decision.scores).map(([k, v]) => (
            <div key={k} style={{
              border: `1px solid ${theme.border}`, borderRadius: 2,
              padding: '3px 6px', fontSize: 8, color: theme.accent,
            }}>
              {k.toUpperCase()}: <span style={{ color: '#fff' }}>{typeof v === 'number' ? v.toFixed(2) : String(v)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Chat */}
      <div style={{ borderTop: `1px solid ${theme.border}`, paddingTop: 10 }}>
        <div style={{ color: '#888', fontSize: 9, marginBottom: 6 }}>ASK CEO</div>
        <div style={{ maxHeight: 80, overflowY: 'auto', marginBottom: 8 }}>
          {chatHistory.map((h, i) => (
            <div key={i} style={{ marginBottom: 6, fontSize: 9 }}>
              <div style={{ color: theme.accent }}>{'>'} {h.q}</div>
              <div style={{ color: '#ccc', paddingLeft: 8 }}>{h.a}</div>
            </div>
          ))}
          {loading && <div style={{ color: '#666', fontSize: 9 }}>CEO is thinking…</div>}
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <input
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && sendChat()}
            placeholder="Ask a question…"
            style={{
              flex: 1, background: '#000', border: `1px solid ${theme.border}`,
              color: theme.text, padding: '4px 8px', fontSize: 9,
              borderRadius: 2, outline: 'none', fontFamily: 'monospace',
            }}
          />
          <button
            onClick={sendChat}
            style={{
              background: theme.accent, color: '#000', border: 'none',
              padding: '4px 10px', fontSize: 9, cursor: 'pointer', borderRadius: 2,
              fontFamily: 'monospace', fontWeight: 'bold',
            }}
          >
            ASK
          </button>
        </div>
      </div>
    </div>
  );
}

function MissionBoardModal({ theme }: { theme: any }) {
  const missions = useWorldStore((s) => s.missions);
  const stages = ['SIGNAL', 'RISK', 'EXECUTION', 'MONITORING', 'CLOSED'];

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 8 }}>
        {stages.map((stage) => {
          const stageMissions = missions.filter(
            (m) => m.stage.toUpperCase() === stage || (stage === 'CLOSED' && m.status === 'completed'),
          );
          return (
            <div key={stage} style={{
              minWidth: 110, border: `1px solid ${theme.border}`,
              borderRadius: 2, padding: 8, background: '#00000040',
            }}>
              <div style={{
                color: theme.accent, fontSize: 8, marginBottom: 8,
                fontFamily: 'monospace', fontWeight: 'bold', textAlign: 'center',
              }}>
                {stage} ({stageMissions.length})
              </div>
              {stageMissions.length === 0 && (
                <div style={{ color: '#444', fontSize: 8, textAlign: 'center', ...pixel }}>—</div>
              )}
              {stageMissions.map((m) => (
                <div key={m.id} style={{
                  background: '#111', border: `1px solid ${
                    m.status === 'failed' ? '#ff4444' :
                    m.status === 'completed' ? '#00ff88' : theme.border
                  }`,
                  borderRadius: 2, padding: '4px 6px', marginBottom: 4,
                  fontSize: 8, color: theme.text, fontFamily: 'monospace',
                }}>
                  <div style={{ fontWeight: 'bold' }}>{m.name}</div>
                  <div style={{ color: '#666', marginTop: 2 }}>
                    {new Date(m.updated_at).toLocaleTimeString()}
                  </div>
                </div>
              ))}
            </div>
          );
        })}
      </div>
      <div style={{ color: '#555', fontSize: 8, marginTop: 8, ...pixel }}>
        {missions.length} total missions
      </div>
    </div>
  );
}

function RiskCenterModal({ theme }: { theme: any }) {
  const [data, setData] = useState<any>(null);
  useEffect(() => { fetchRoomData('/api/system/health').then(setData); }, []);

  const subs = data?.subsystems ?? {};

  return (
    <div>
      <div style={{
        color: data?.overall_status === 'ALIVE' ? '#00ff88' :
               data?.overall_status === 'STALE' ? '#ffaa00' : '#ff4444',
        fontSize: 14, fontWeight: 'bold', ...pixel, marginBottom: 12,
      }}>
        ● SYSTEM: {data?.overall_status ?? 'LOADING…'}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
        {Object.entries(subs).map(([name, info]: [string, any]) => (
          <div key={name} style={{
            border: `1px solid ${info.status === 'ALIVE' ? '#00ff8830' : '#ff444430'}`,
            borderRadius: 2, padding: '5px 8px', background: '#00000040',
          }}>
            <div style={{
              color: info.status === 'ALIVE' ? '#00ff88' : info.status === 'STALE' ? '#ffaa00' : '#ff4444',
              fontSize: 8, ...pixel,
            }}>
              {info.status === 'ALIVE' ? '●' : info.status === 'STALE' ? '◉' : '○'} {name}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function PortfolioVaultModal({ theme }: { theme: any }) {
  const paper = useWorldStore((s) => s.paper);
  const pos = paper?.open_position;
  const pnlColor = (paper?.total_pnl ?? 0) >= 0 ? '#00ff88' : '#ff4444';
  const uPnlColor = (pos?.unrealized_pnl ?? 0) >= 0 ? '#00ff88' : '#ff4444';

  return (
    <div>
      {/* Summary row */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
        {[
          { label: 'TOTAL P&L', value: `${(paper?.total_pnl ?? 0) >= 0 ? '+' : ''}${(paper?.total_pnl ?? 0).toFixed(2)} USDT`, color: pnlColor },
          { label: 'WIN RATE', value: `${((paper?.win_rate ?? 0) * 100).toFixed(1)}%`, color: theme.accent },
          { label: 'TRADES', value: String(paper?.total_trades ?? 0), color: theme.text },
        ].map((s) => (
          <div key={s.label} style={{
            flex: 1, border: `1px solid ${theme.border}`, borderRadius: 2,
            padding: '8px 10px', background: '#00000040',
          }}>
            <div style={{ color: '#666', fontSize: 8, ...pixel }}>{s.label}</div>
            <div style={{ color: s.color, fontSize: 13, fontWeight: 'bold', ...pixel }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Open position */}
      {pos ? (
        <div style={{
          border: `1px solid ${pos.side === 'LONG' ? '#00ff8850' : '#ff444450'}`,
          borderRadius: 2, padding: 12, background: '#00000060',
        }}>
          <div style={{ color: '#888', fontSize: 8, ...pixel, marginBottom: 6 }}>OPEN POSITION</div>
          <div style={{ display: 'flex', gap: 12 }}>
            <div>
              <div style={{ color: pos.side === 'LONG' ? '#00ff88' : '#ff4444', fontSize: 16, fontWeight: 'bold', ...pixel }}>
                {pos.side}
              </div>
              <div style={{ color: '#888', fontSize: 8, ...pixel }}>{pos.size} BTC</div>
            </div>
            <div>
              <div style={{ color: '#fff', fontSize: 12, ...pixel }}>{pos.entry_price.toLocaleString()}</div>
              <div style={{ color: '#888', fontSize: 8, ...pixel }}>ENTRY</div>
            </div>
            <div>
              <div style={{ color: uPnlColor, fontSize: 12, fontWeight: 'bold', ...pixel }}>
                {(pos.unrealized_pnl >= 0 ? '+' : '')}{pos.unrealized_pnl.toFixed(2)} USDT
              </div>
              <div style={{ color: '#888', fontSize: 8, ...pixel }}>UNREALIZED P&L</div>
            </div>
          </div>
        </div>
      ) : (
        <div style={{ color: '#555', fontSize: 10, textAlign: 'center', padding: 16, ...pixel, border: `1px solid ${theme.border}`, borderRadius: 2 }}>
          No open position
        </div>
      )}
    </div>
  );
}

function CommandCenterModal({ theme }: { theme: any }) {
  const [cmdInput, setCmdInput] = useState('');
  const [log, setLog] = useState<{ cmd: string; result: string; ok: boolean }[]>([]);
  const [loading, setLoading] = useState(false);

  const execCmd = useCallback(async () => {
    if (!cmdInput.trim()) return;
    const cmd = cmdInput.trim();
    setCmdInput('');
    setLoading(true);
    const res = await sendCommand(cmd);
    setLog((l) => [...l, { cmd, result: res.message ?? JSON.stringify(res), ok: res.success }]);
    setLoading(false);
  }, [cmdInput]);

  const quickCmds = ['pause trader', 'resume trader', 'show positions', 'show pnl', 'show risk', 'paper mode on'];

  return (
    <div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 12 }}>
        {quickCmds.map((cmd) => (
          <button key={cmd} onClick={() => { setCmdInput(cmd); }}
            style={{
              background: '#111', border: `1px solid ${theme.border}`, color: theme.accent,
              padding: '3px 8px', fontSize: 8, cursor: 'pointer', borderRadius: 2, fontFamily: 'monospace',
            }}>
            {cmd}
          </button>
        ))}
      </div>
      <div style={{
        background: '#000', border: `1px solid ${theme.border}`, borderRadius: 2,
        padding: 10, height: 140, overflowY: 'auto', marginBottom: 10,
        fontSize: 9, fontFamily: 'monospace',
      }}>
        {log.map((l, i) => (
          <div key={i} style={{ marginBottom: 6 }}>
            <div style={{ color: theme.accent }}>{'>'} {l.cmd}</div>
            <div style={{ color: l.ok ? '#00ff88' : '#ff4444', paddingLeft: 12 }}>{l.result}</div>
          </div>
        ))}
        {loading && <div style={{ color: '#666' }}>Executing…</div>}
        {log.length === 0 && !loading && (
          <div style={{ color: '#444' }}>Type a command or click a quick command above.</div>
        )}
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        <input value={cmdInput} onChange={(e) => setCmdInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && execCmd()}
          placeholder="Type command…"
          style={{
            flex: 1, background: '#000', border: `1px solid ${theme.border}`,
            color: theme.text, padding: '5px 8px', fontSize: 9, borderRadius: 2,
            outline: 'none', fontFamily: 'monospace',
          }}
        />
        <button onClick={execCmd}
          style={{
            background: theme.accent, color: '#000', border: 'none',
            padding: '5px 12px', fontSize: 9, cursor: 'pointer', borderRadius: 2,
            fontFamily: 'monospace', fontWeight: 'bold',
          }}>
          EXEC
        </button>
      </div>
    </div>
  );
}

function MlLabModal({ theme }: { theme: any }) {
  const [data, setData] = useState<any>(null);
  useEffect(() => { fetchRoomData('/api/ml/status').then(setData); }, []);

  return (
    <div>
      {data ? (
        <div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
            {['meta_label', 'confidence_calibrator', 'outcome_predictor'].map((m) => {
              const info = data[m] ?? data.active_models?.[m];
              return (
                <div key={m} style={{
                  border: `1px solid ${theme.border}`, borderRadius: 2, padding: 8,
                  background: '#00000040',
                }}>
                  <div style={{ color: '#888', fontSize: 8, ...pixel, marginBottom: 4 }}>
                    {m.replace(/_/g, ' ').toUpperCase()}
                  </div>
                  <div style={{ color: info ? theme.accent : '#666', fontSize: 10, ...pixel }}>
                    {info?.version ?? info?.model_type ?? 'Not loaded'}
                  </div>
                  {info?.accuracy && (
                    <div style={{ color: theme.success, fontSize: 8, ...pixel }}>
                      Acc: {(info.accuracy * 100).toFixed(1)}%
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          <div style={{ color: '#555', fontSize: 8, ...pixel }}>
            Last updated: {data.last_updated ?? data.timestamp ?? '—'}
          </div>
        </div>
      ) : (
        <div style={{ color: '#555', ...pixel, textAlign: 'center', padding: 20 }}>Loading ML status…</div>
      )}
    </div>
  );
}

function TeleportHubModal({ onTeleport }: { theme: any; onTeleport: (id: string) => void }) {
  return (
    <div>
      <div style={{ color: '#00ffff', fontSize: 9, marginBottom: 10, fontFamily: 'monospace' }}>
        SELECT DESTINATION
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
        {ROOM_DEFINITIONS.filter((r) => r.id !== 'teleport').map((room) => (
          <button key={room.id} onClick={() => onTeleport(room.id)}
            style={{
              background: '#00000060', border: `1px solid ${room.accentColor.toString(16).padStart(6, '0').replace(/^/, '#')}`,
              color: room.labelColor, padding: '6px 10px', fontSize: 8, cursor: 'pointer',
              borderRadius: 2, fontFamily: 'monospace', textAlign: 'left',
              display: 'flex', alignItems: 'center', gap: 6,
            }}>
            ▶ {room.name}
          </button>
        ))}
      </div>
    </div>
  );
}

function GenericRoomModal({ roomId, theme }: { roomId: string; theme: any }) {
  const [data, setData] = useState<any>(null);
  const room = ROOM_DEFINITIONS.find((r) => r.id === roomId);

  useEffect(() => {
    if (room?.apiEndpoint) fetchRoomData(room.apiEndpoint).then(setData);
  }, [roomId]);

  return (
    <div>
      {room && (
        <div style={{ color: '#888', fontSize: 9, ...pixel, marginBottom: 8 }}>
          {room.description}
        </div>
      )}
      {data ? (
        <pre style={{
          background: '#000', border: `1px solid ${theme.border}`, borderRadius: 2,
          padding: 10, fontSize: 8, color: theme.accent, overflowY: 'auto',
          maxHeight: 180, fontFamily: 'monospace', whiteSpace: 'pre-wrap',
        }}>
          {JSON.stringify(data, null, 2)}
        </pre>
      ) : (
        <div style={{ color: '#555', ...pixel, textAlign: 'center', padding: 20 }}>Loading…</div>
      )}
    </div>
  );
}

// ── Main Modal ────────────────────────────────────────────────────────────────

const MODAL_TITLES: Record<string, string> = {
  ceo: '👔 CEO Room',
  mission_board: '🎯 Mission Board',
  risk_center: '⚠️ Risk Center',
  portfolio_vault: '💼 Portfolio Vault',
  replay_theater: '🎬 Replay Theater',
  ml_lab: '🤖 ML Laboratory',
  intelligence_lab: '📊 Intelligence Lab',
  futures_lab: '📈 Futures Lab',
  command_center: '💻 Command Center',
  server_room: '🖥️ Server Room',
  data_center: '💾 Data Center',
  training_room: '🧠 Training Room',
  meeting_room: '🤝 Meeting Room',
  emergency_room: '🚨 Emergency Room',
  teleport_hub: '🌀 Teleport Hub',
  central_plaza: '🏛️ Central Plaza',
  none: '',
};

interface InteractionModalProps {
  onTeleport: (roomId: string) => void;
}

export default function InteractionModal({ onTeleport }: InteractionModalProps) {
  const { activeModal, activeRoomId, closeModal, theme } = useWorldStore();
  const colors = THEME_COLORS[theme];
  const isOpen = activeModal !== 'none';

  const renderContent = () => {
    switch (activeModal) {
      case 'ceo':            return <CeoModal theme={colors} />;
      case 'mission_board':  return <MissionBoardModal theme={colors} />;
      case 'risk_center':    return <RiskCenterModal theme={colors} />;
      case 'portfolio_vault':return <PortfolioVaultModal theme={colors} />;
      case 'ml_lab':         return <MlLabModal theme={colors} />;
      case 'command_center': return <CommandCenterModal theme={colors} />;
      case 'teleport_hub':   return <TeleportHubModal theme={colors} onTeleport={onTeleport} />;
      default:
        return <GenericRoomModal roomId={activeRoomId ?? ''} theme={colors} />;
    }
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={closeModal}
            style={{
              position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.6)',
              zIndex: 200, cursor: 'pointer',
            }}
          />
          {/* Panel */}
          <motion.div
            initial={{ opacity: 0, scale: 0.9, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9, y: 20 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            style={{
              position: 'absolute', top: '50%', left: '50%',
              transform: 'translate(-50%, -50%)',
              width: 480, maxWidth: '92vw', maxHeight: '80vh',
              background: colors.panel,
              border: `2px solid ${colors.accent}`,
              borderRadius: 4, padding: 20, zIndex: 201,
              overflow: 'hidden', display: 'flex', flexDirection: 'column',
              boxShadow: `0 0 30px ${colors.accent}40`,
            }}
          >
            {/* Header */}
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              marginBottom: 14, borderBottom: `1px solid ${colors.border}`, paddingBottom: 10,
            }}>
              <div style={{
                color: colors.accent, fontSize: 12, fontWeight: 'bold',
                fontFamily: 'monospace', letterSpacing: 1,
              }}>
                {MODAL_TITLES[activeModal] ?? activeModal.toUpperCase()}
              </div>
              <button onClick={closeModal}
                style={{
                  background: 'none', border: `1px solid ${colors.border}`,
                  color: colors.text, cursor: 'pointer', borderRadius: 2,
                  padding: '2px 8px', fontSize: 10, fontFamily: 'monospace',
                }}>
                ✕
              </button>
            </div>
            {/* Content */}
            <div style={{ overflowY: 'auto', flex: 1 }}>
              {renderContent()}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
