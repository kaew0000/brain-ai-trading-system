// ============================================================
// Brain Bot V15 — Theme Toolbar
// Floating bottom toolbar for theme switching, audio toggle,
// zoom controls and keyboard shortcut hints.
// ============================================================

import { useWorldStore, THEME_COLORS } from '../worldStore';
import type { WorldTheme } from '../types/world.types';

const THEMES: Array<{ id: WorldTheme; label: string; dot: string }> = [
  { id: 'cyberpunk', label: 'CYBER', dot: '#00ff88' },
  { id: 'dark',      label: 'DARK',  dot: '#58a6ff' },
  { id: 'retro',     label: 'RETRO', dot: '#00ff00' },
  { id: 'light',     label: 'LIGHT', dot: '#3355ff' },
];

interface ThemeToolbarProps {
  onSearch: () => void;
}

export default function ThemeToolbar({ onSearch }: ThemeToolbarProps) {
  const { theme, setTheme, audioEnabled, toggleAudio } = useWorldStore();
  const colors = THEME_COLORS[theme];

  return (
    <div style={{
      position: 'absolute', bottom: 12, left: '50%',
      transform: 'translateX(-50%)',
      display: 'flex', alignItems: 'center', gap: 6,
      background: colors.panel,
      border: `1px solid ${colors.border}`,
      borderRadius: 3, padding: '5px 10px',
      zIndex: 100, pointerEvents: 'all',
      boxShadow: `0 0 12px ${colors.accent}20`,
    }}>
      {/* Theme buttons */}
      {THEMES.map((t) => (
        <button
          key={t.id}
          onClick={() => setTheme(t.id)}
          title={`Switch to ${t.label} theme`}
          style={{
            background: theme === t.id ? `${t.dot}20` : 'none',
            border: `1px solid ${theme === t.id ? t.dot : colors.border}`,
            color: theme === t.id ? t.dot : '#555',
            padding: '3px 8px', fontSize: 8, cursor: 'pointer', borderRadius: 2,
            fontFamily: 'monospace', fontWeight: 'bold',
            display: 'flex', alignItems: 'center', gap: 4,
          }}
        >
          <div style={{ width: 5, height: 5, background: t.dot, borderRadius: '50%' }} />
          {t.label}
        </button>
      ))}

      <div style={{ width: 1, height: 14, background: colors.border }} />

      {/* Audio toggle */}
      <button
        onClick={toggleAudio}
        title="Toggle audio"
        style={{
          background: audioEnabled ? `${colors.accent}20` : 'none',
          border: `1px solid ${audioEnabled ? colors.accent : colors.border}`,
          color: audioEnabled ? colors.accent : '#555',
          padding: '3px 8px', fontSize: 9, cursor: 'pointer', borderRadius: 2,
          fontFamily: 'monospace',
        }}
      >
        {audioEnabled ? '♪ ON' : '♪ OFF'}
      </button>

      <div style={{ width: 1, height: 14, background: colors.border }} />

      {/* Search hint */}
      <button
        onClick={onSearch}
        style={{
          background: 'none', border: `1px solid ${colors.border}`,
          color: '#666', padding: '3px 8px', fontSize: 8, cursor: 'pointer',
          borderRadius: 2, fontFamily: 'monospace', display: 'flex', alignItems: 'center', gap: 4,
        }}
      >
        ⌕ <kbd style={{ color: '#888', background: '#111', border: `1px solid ${colors.border}`, borderRadius: 1, padding: '0 3px', fontSize: 7 }}>Ctrl+K</kbd>
      </button>

      <div style={{ width: 1, height: 14, background: colors.border }} />

      {/* Controls hint */}
      <span style={{ color: '#444', fontSize: 7, fontFamily: 'monospace' }}>
        WASD/↑↓←→ move · E interact · scroll zoom
      </span>
    </div>
  );
}
