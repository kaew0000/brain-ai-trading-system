// ============================================================
// Brain Bot V15 — Minimap
// Top-right minimap showing the full HQ with player position,
// NPC positions, room markers, and click-to-teleport.
// ============================================================

import { useRef, useEffect, useCallback } from 'react';
import { useWorldStore, THEME_COLORS } from '../worldStore';
import { ROOM_DEFINITIONS, MAP_COLS, MAP_ROWS } from '../Room';
import type { WorldMap } from '../types/world.types';

const MINIMAP_W = 180;
const MINIMAP_H = 108; // ~same aspect ratio as map (120:72 = 5:3)

const TILE_W = MINIMAP_W / MAP_COLS; // ~1.5 px per tile
const TILE_H = MINIMAP_H / MAP_ROWS;

// Color table for tile types on minimap
const TILE_COLORS: Record<string, string> = {
  void:               '#000000',
  grass:              '#0a1a0a',
  path:               '#2a3040',
  water:              '#061228',
  wall:               '#050508',
  floor_ceo:          '#12124a',
  floor_mission:      '#2e0a3f',
  floor_risk:         '#3f0a0a',
  floor_intelligence: '#0a2510',
  floor_futures:      '#251500',
  floor_ml:           '#0f0f40',
  floor_command:      '#002020',
  floor_portfolio:    '#251e00',
  floor_replay:       '#250025',
  floor_server:       '#101010',
  floor_data:         '#0f0f18',
  floor_training:     '#0a2020',
  floor_meeting:      '#222235',
  floor_emergency:    '#500000',
  floor_teleport:     '#003030',
  floor_plaza:        '#22222a',
};

const ROOM_ACCENT: Record<string, string> = {
  ceo: '#4444ff', mission: '#aa44ff', risk: '#ff4444',
  intelligence: '#00ff88', futures: '#ff8800', ml_lab: '#4488ff',
  command: '#00cccc', portfolio: '#ddaa00', replay: '#ff44ff',
  server: '#22ff44', data_center: '#6666ff', training: '#00ffaa',
  meeting: '#8888ff', emergency: '#ff0000', teleport: '#00ffff',
  plaza: '#44ddff',
};

interface MinimapProps {
  worldMap: WorldMap | null;
  npcPositions: Array<{ id: string; tx: number; ty: number }>;
  onTeleport: (tx: number, ty: number) => void;
}

export default function Minimap({ worldMap, npcPositions, onTeleport }: MinimapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { playerTileX, playerTileY, theme } = useWorldStore();
  const colors = THEME_COLORS[theme];

  // Draw static base map (only when worldMap changes)
  const baseCanvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (!worldMap) return;

    // Render static base
    const base = document.createElement('canvas');
    base.width = MINIMAP_W;
    base.height = MINIMAP_H;
    const ctx = base.getContext('2d')!;

    for (let ty = 0; ty < MAP_ROWS; ty++) {
      for (let tx = 0; tx < MAP_COLS; tx++) {
        const tile = worldMap.tiles[ty][tx];
        ctx.fillStyle = TILE_COLORS[tile] ?? '#0a0a0a';
        ctx.fillRect(tx * TILE_W, ty * TILE_H, Math.ceil(TILE_W), Math.ceil(TILE_H));
      }
    }

    // Room accent outlines
    for (const room of ROOM_DEFINITIONS) {
      const accent = ROOM_ACCENT[room.id] ?? '#ffffff';
      ctx.strokeStyle = accent + '80';
      ctx.lineWidth = 0.5;
      ctx.strokeRect(
        room.tx * TILE_W, room.ty * TILE_H,
        room.tw * TILE_W, room.th * TILE_H,
      );
    }

    baseCanvasRef.current = base;
  }, [worldMap]);

  // Draw dynamic overlay (player, NPCs)
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !baseCanvasRef.current) return;
    const ctx = canvas.getContext('2d')!;

    // Draw base
    ctx.clearRect(0, 0, MINIMAP_W, MINIMAP_H);
    ctx.drawImage(baseCanvasRef.current, 0, 0);

    // Room name labels
    for (const room of ROOM_DEFINITIONS) {
      const cx = (room.tx + room.tw / 2) * TILE_W;
      const cy = (room.ty + room.th / 2) * TILE_H;
      ctx.fillStyle = (ROOM_ACCENT[room.id] ?? '#fff') + 'aa';
      ctx.font = '3.5px monospace';
      ctx.textAlign = 'center';
      ctx.fillText(room.name.slice(0, 6).toUpperCase(), cx, cy + 1);
    }

    // NPCs (small colored dots)
    for (const npc of npcPositions) {
      const nx = npc.tx * TILE_W;
      const ny = npc.ty * TILE_H;
      ctx.fillStyle = '#ffee00';
      ctx.beginPath();
      ctx.arc(nx, ny, 1.2, 0, Math.PI * 2);
      ctx.fill();
    }

    // Player (bright white triangle)
    const px = playerTileX * TILE_W;
    const py = playerTileY * TILE_H;
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.moveTo(px, py - 3);
    ctx.lineTo(px - 2, py + 1);
    ctx.lineTo(px + 2, py + 1);
    ctx.closePath();
    ctx.fill();

    // Player glow
    ctx.fillStyle = 'rgba(255,255,255,0.25)';
    ctx.beginPath();
    ctx.arc(px, py, 4, 0, Math.PI * 2);
    ctx.fill();
  }, [playerTileX, playerTileY, npcPositions]);

  const handleClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = (e.target as HTMLCanvasElement).getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const tx = Math.floor(mx / TILE_W);
    const ty = Math.floor(my / TILE_H);
    onTeleport(tx, ty);
  }, [onTeleport]);

  return (
    <div style={{
      position: 'absolute', top: 8, left: 8,
      border: `1px solid ${colors.accent}60`,
      borderRadius: 2, overflow: 'hidden',
      boxShadow: `0 0 12px ${colors.accent}20`,
      zIndex: 90,
    }}>
      {/* Header */}
      <div style={{
        background: colors.panel, padding: '3px 8px',
        borderBottom: `1px solid ${colors.border}`,
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <span style={{ color: colors.accent, fontSize: 7, fontFamily: 'monospace', fontWeight: 'bold', letterSpacing: 1 }}>
          MINIMAP
        </span>
        <span style={{ color: '#555', fontSize: 7, fontFamily: 'monospace' }}>
          {playerTileX},{playerTileY}
        </span>
      </div>
      {/* Canvas */}
      <canvas
        ref={canvasRef}
        width={MINIMAP_W}
        height={MINIMAP_H}
        onClick={handleClick}
        style={{ display: 'block', cursor: 'crosshair' }}
      />
      {/* Legend */}
      <div style={{
        background: colors.panel, padding: '3px 8px',
        borderTop: `1px solid ${colors.border}`,
        display: 'flex', gap: 8,
      }}>
        {[
          { color: '#ffffff', label: 'YOU' },
          { color: '#ffee00', label: 'NPC' },
          { color: '#4488ff', label: 'ROOM' },
        ].map((l) => (
          <div key={l.label} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
            <div style={{ width: 5, height: 5, background: l.color, borderRadius: '50%' }} />
            <span style={{ color: '#666', fontSize: 6, fontFamily: 'monospace' }}>{l.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
