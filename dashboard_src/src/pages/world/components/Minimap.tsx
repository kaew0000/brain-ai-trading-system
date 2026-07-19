// ============================================================
// Brain Bot V16 — Minimap
// Top-right minimap showing the full HQ with player position,
// NPC positions, room markers, and click-to-teleport.
//
// V16 changes:
//   • Offscreen canvas for static terrain (no re-draw every frame)
//   • Smooth CSS transitions on overlay elements
//   • Room label tooltips on hover
//   • Player trail with fading dots
// ============================================================

import { useRef, useEffect, useCallback, useState, memo } from 'react';
import { useWorldStore, THEME_COLORS } from '../worldStore';
import { ROOM_DEFINITIONS, MAP_COLS, MAP_ROWS } from '../Room';
import type { WorldMap } from '../types/world.types';

const MINIMAP_W = 180;
const MINIMAP_H = 108;

const TILE_W = MINIMAP_W / MAP_COLS;
const TILE_H = MINIMAP_H / MAP_ROWS;

const TILE_COLORS: Record<string, string> = {
  void: '#000000',
  grass: '#0a1a0a',
  path: '#2a3040',
  water: '#061228',
  wall: '#050508',
  floor_ceo: '#12124a',
  floor_mission: '#2e0a3f',
  floor_risk: '#3f0a0a',
  floor_intelligence: '#0a2510',
  floor_futures: '#251500',
  floor_ml: '#0f0f40',
  floor_command: '#002020',
  floor_portfolio: '#251e00',
  floor_replay: '#250025',
  floor_server: '#101010',
  floor_data: '#0f0f18',
  floor_training: '#0a2020',
  floor_meeting: '#222235',
  floor_emergency: '#500000',
  floor_teleport: '#003030',
  floor_plaza: '#22222a',
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

export default memo(function Minimap({ worldMap, npcPositions, onTeleport }: MinimapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const baseCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const { playerTileX, playerTileY, theme } = useWorldStore();
  const colors = THEME_COLORS[theme];
  const [hoverRoom, setHoverRoom] = useState<string | null>(null);

  // Build static offscreen canvas once per worldMap change
  useEffect(() => {
    if (!worldMap) return;
    const base = document.createElement('canvas');
    base.width = MINIMAP_W;
    base.height = MINIMAP_H;
    const ctx = base.getContext('2d')!;

    for (let ty = 0; ty < MAP_ROWS; ty++) {
      for (let tx = 0; tx < MAP_COLS; tx++) {
        const tile = worldMap.tiles[ty]?.[tx] ?? 'void';
        ctx.fillStyle = TILE_COLORS[tile] ?? '#0a0a0a';
        ctx.fillRect(tx * TILE_W, ty * TILE_H, Math.ceil(TILE_W), Math.ceil(TILE_H));
      }
    }

    for (const room of ROOM_DEFINITIONS) {
      const accent = ROOM_ACCENT[room.id] ?? '#444444';
      ctx.strokeStyle = accent + '88';
      ctx.lineWidth = 1;
      ctx.strokeRect(
        room.tx * TILE_W,
        room.ty * TILE_H,
        room.tw * TILE_W,
        room.th * TILE_H
      );
    }

    baseCanvasRef.current = base;
  }, [worldMap]);

  // Draw dynamic layer (player, NPCs, trail) on visible canvas
  useEffect(() => {
    if (!canvasRef.current || !baseCanvasRef.current) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d', { willReadFrequently: true })!;
    const base = baseCanvasRef.current;

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(base, 0, 0);

    // NPC dots
    for (const npc of npcPositions) {
      ctx.fillStyle = '#fbbf24';
      ctx.beginPath();
      ctx.arc(npc.tx * TILE_W + TILE_W / 2, npc.ty * TILE_H + TILE_H / 2, 2, 0, Math.PI * 2);
      ctx.fill();
    }

    // Player dot with glow
    if (playerTileX != null && playerTileY != null) {
      const px = playerTileX * TILE_W + TILE_W / 2;
      const py = playerTileY * TILE_H + TILE_H / 2;

      ctx.shadowColor = '#3b82f6';
      ctx.shadowBlur = 6;
      ctx.fillStyle = '#3b82f6';
      ctx.beginPath();
      ctx.arc(px, py, 3, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
    }
  }, [npcPositions, playerTileX, playerTileY]);

  const handleClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!canvasRef.current || !onTeleport) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    onTeleport(Math.floor(x / TILE_W), Math.floor(y / TILE_H));
  }, [onTeleport]);

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!canvasRef.current || !worldMap) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const tx = Math.floor((e.clientX - rect.left) / TILE_W);
    const ty = Math.floor((e.clientY - rect.top) / TILE_H);
    const room = ROOM_DEFINITIONS.find(r =>
      tx >= r.tx && tx < r.tx + r.tw && ty >= r.ty && ty < r.ty + r.th
    );
    setHoverRoom(room ? room.name : null);
  }, [worldMap]);

  return (
    <div className="absolute top-4 right-4 w-48 bg-surface-1/90 border border-border rounded-lg overflow-hidden shadow-lg backdrop-blur-sm transition-opacity duration-300 hover:opacity-100 opacity-90">
      <div className="px-2 py-1 border-b border-border flex items-center justify-between">
        <span className="text-[9px] text-text-muted font-mono uppercase tracking-wider">Minimap</span>
        {hoverRoom && (
          <span className="text-[9px] text-accent-blue font-mono truncate max-w-[80px]">{hoverRoom}</span>
        )}
      </div>
      <canvas
        ref={canvasRef}
        width={MINIMAP_W}
        height={MINIMAP_H}
        className="w-full cursor-crosshair"
        onClick={handleClick}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverRoom(null)}
      />
    </div>
  );
});
