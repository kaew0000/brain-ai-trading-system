// ============================================================
// Brain Bot V15 — Search Bar (Ctrl+K)
// Spotlight-style search that finds rooms, NPCs, and agents,
// then teleports the player to the result.
// ============================================================

import { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useWorldStore, THEME_COLORS } from '../worldStore';
import { ROOM_DEFINITIONS, NPC_DEFINITIONS } from '../Room';

interface SearchResult {
  id: string;
  type: 'room' | 'npc' | 'agent';
  label: string;
  sublabel: string;
  action: () => void;
}

interface SearchBarProps {
  open: boolean;
  onClose: () => void;
  onTeleportRoom: (roomId: string) => void;
  onTeleportNpc: (npcId: string) => void;
}

export default function SearchBar({
  open, onClose, onTeleportRoom, onTeleportNpc,
}: SearchBarProps) {
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const { theme, agents } = useWorldStore();
  const colors = THEME_COLORS[theme];

  // Build search index
  const allResults: SearchResult[] = [
    ...ROOM_DEFINITIONS.map((r): SearchResult => ({
      id: r.id, type: 'room',
      label: r.name,
      sublabel: r.description,
      action: () => { onTeleportRoom(r.id); onClose(); },
    })),
    ...NPC_DEFINITIONS.map((n): SearchResult => ({
      id: n.id, type: 'npc',
      label: n.name,
      sublabel: n.role,
      action: () => { onTeleportNpc(n.id); onClose(); },
    })),
    ...Object.entries(agents).map(([k, v]): SearchResult => ({
      id: k, type: 'agent',
      label: v.name ?? k,
      sublabel: `Status: ${v.status} — Confidence: ${Math.round(v.confidence * 100)}%`,
      action: () => {
        // Find NPC for this agent
        const npc = NPC_DEFINITIONS.find((n) => n.id.includes(k) || k.includes(n.id.replace('_agent', '')));
        if (npc) { onTeleportNpc(npc.id); onClose(); }
      },
    })),
  ];

  const filtered = query.trim()
    ? allResults.filter((r) =>
        r.label.toLowerCase().includes(query.toLowerCase()) ||
        r.sublabel.toLowerCase().includes(query.toLowerCase())
      )
    : allResults.slice(0, 8);

  // Focus on open
  useEffect(() => {
    if (open) {
      setQuery(''); setSelected(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  const handleKey = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelected((s) => Math.min(s + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelected((s) => Math.max(s - 1, 0));
    } else if (e.key === 'Enter') {
      filtered[selected]?.action();
    } else if (e.key === 'Escape') {
      onClose();
    }
  }, [filtered, selected, onClose]);

  const typeIcon: Record<string, string> = { room: '🏢', npc: '🤖', agent: '📊' };
  const typeLabel: Record<string, string> = { room: 'ROOM', npc: 'NPC', agent: 'AGENT' };

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={onClose}
            style={{
              position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.7)',
              zIndex: 300, cursor: 'pointer',
            }}
          />
          {/* Search panel */}
          <motion.div
            initial={{ opacity: 0, y: -20, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -20, scale: 0.97 }}
            transition={{ duration: 0.14 }}
            style={{
              position: 'absolute', top: '15%', left: '50%',
              transform: 'translateX(-50%)',
              width: 440, maxWidth: '90vw',
              background: colors.panel,
              border: `2px solid ${colors.accent}`,
              borderRadius: 4, zIndex: 301,
              boxShadow: `0 0 40px ${colors.accent}40`,
              overflow: 'hidden',
            }}
          >
            {/* Input */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '10px 14px',
              borderBottom: `1px solid ${colors.border}`,
            }}>
              <span style={{ color: colors.accent, fontSize: 14 }}>⌕</span>
              <input
                ref={inputRef}
                value={query}
                onChange={(e) => { setQuery(e.target.value); setSelected(0); }}
                onKeyDown={handleKey}
                placeholder="Search rooms, NPCs, agents…"
                style={{
                  flex: 1, background: 'none', border: 'none', outline: 'none',
                  color: colors.text, fontSize: 11, fontFamily: 'monospace',
                }}
              />
              <kbd style={{
                color: '#555', fontSize: 8, background: '#111',
                border: `1px solid ${colors.border}`, borderRadius: 2,
                padding: '1px 4px', fontFamily: 'monospace',
              }}>ESC</kbd>
            </div>

            {/* Results */}
            <div style={{ maxHeight: 320, overflowY: 'auto' }}>
              {filtered.length === 0 && (
                <div style={{ color: '#555', fontSize: 9, padding: 16, textAlign: 'center', fontFamily: 'monospace' }}>
                  No results for "{query}"
                </div>
              )}
              {filtered.map((r, i) => (
                <div
                  key={r.id + i}
                  onClick={r.action}
                  onMouseEnter={() => setSelected(i)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 10,
                    padding: '8px 14px', cursor: 'pointer',
                    background: i === selected ? `${colors.accent}14` : 'transparent',
                    borderLeft: i === selected ? `2px solid ${colors.accent}` : '2px solid transparent',
                    transition: 'background 0.1s',
                  }}
                >
                  <span style={{ fontSize: 14 }}>{typeIcon[r.type]}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ color: colors.text, fontSize: 9, fontFamily: 'monospace', fontWeight: 'bold' }}>
                      {r.label}
                    </div>
                    <div style={{ color: '#666', fontSize: 8, fontFamily: 'monospace', marginTop: 1 }}>
                      {r.sublabel}
                    </div>
                  </div>
                  <div style={{
                    color: colors.accent, fontSize: 7, background: `${colors.accent}20`,
                    border: `1px solid ${colors.accent}40`, borderRadius: 2,
                    padding: '1px 5px', fontFamily: 'monospace',
                  }}>
                    {typeLabel[r.type]}
                  </div>
                  {i === selected && (
                    <kbd style={{
                      color: '#555', fontSize: 7, background: '#111',
                      border: `1px solid ${colors.border}`, borderRadius: 2,
                      padding: '1px 4px', fontFamily: 'monospace',
                    }}>↵</kbd>
                  )}
                </div>
              ))}
            </div>

            {/* Footer */}
            <div style={{
              borderTop: `1px solid ${colors.border}`,
              padding: '5px 14px', display: 'flex', gap: 10,
            }}>
              {[['↑↓', 'navigate'], ['↵', 'teleport'], ['esc', 'close']].map(([key, label]) => (
                <span key={key} style={{ fontSize: 7, fontFamily: 'monospace', color: '#555' }}>
                  <kbd style={{ color: '#888', background: '#111', border: `1px solid ${colors.border}`, borderRadius: 1, padding: '0 3px' }}>{key}</kbd>
                  {' '}{label}
                </span>
              ))}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
