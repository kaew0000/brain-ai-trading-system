// ============================================================
// Brain Bot V16 — World HQ Page
// Root React component for the 2D pixel-art trading HQ.
// Mounts Phaser, bridges events to React overlays, manages
// the full module lifecycle cleanly.
//
// V16 changes:
//   • React.memo to prevent parent re-render cascades
//   • Throttled NPC position updates (200 ms)
//   • Named event listener cleanup (no removeAllListeners)
//   • Loading overlay while Phaser boots
// ============================================================

import { useEffect, useRef, useState, useCallback, memo } from 'react';
import Phaser from 'phaser';
import { WorldScene, WORLD_EVENTS } from './WorldScene';
import { startWorldApi, stopWorldApi } from './worldApi';
import { useWorldStore, THEME_COLORS } from './worldStore';
import { buildWorldMap } from './MapLoader';
import { ROOM_DEFINITIONS } from './Room';
import type { WorldMap } from './types/world.types';
import { useThrottle } from '@/hooks/useThrottle';

import WorldOverlay from './components/WorldOverlay';
import SearchBar from './components/SearchBar';
import ThemeToolbar from './components/ThemeToolbar';
import InteractionModal from './components/InteractionModal';

// ── Helpers ───────────────────────────────────────────────────────────────────

function closestRoomId(tx: number, ty: number): string {
  let best = 'plaza';
  let bestDist = Infinity;
  for (const room of ROOM_DEFINITIONS) {
    const cx = room.tx + room.tw / 2;
    const cy = room.ty + room.th / 2;
    const d = Math.hypot(cx - tx, cy - ty);
    if (d < bestDist) { bestDist = d; best = room.id; }
  }
  return best;
}

function createPhaserConfig(parent: HTMLElement): Phaser.Types.Core.GameConfig {
  return {
    type: Phaser.AUTO,
    parent,
    width: '100%',
    height: '100%',
    backgroundColor: '#070714',
    pixelArt: true,
    antialias: false,
    roundPixels: true,
    scene: [WorldScene],
    physics: {
      default: 'arcade',
      arcade: { gravity: { x: 0, y: 0 }, debug: false },
    },
    scale: {
      mode: Phaser.Scale.RESIZE,
      autoCenter: Phaser.Scale.CENTER_BOTH,
    },
  };
}

// ── WorldPage ─────────────────────────────────────────────────────────────────

export default memo(function WorldPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const gameRef = useRef<Phaser.Game | null>(null);
  const sceneRef = useRef<WorldScene | null>(null);

  const [worldMap, setWorldMap] = useState<WorldMap | null>(null);
  const [npcPositions, setNpcPositions] = useState<Array<{ id: string; tx: number; ty: number }>>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [ready, setReady] = useState(false);

  const { theme, openModal } = useWorldStore();
  const colors = THEME_COLORS[theme];

  // Throttle NPC position updates to 200 ms — prevents React re-render storm
  // when player walks across many tiles quickly.
  const throttledSetNpcPositions = useThrottle(
    useCallback((positions: Array<{ id: string; tx: number; ty: number }>) => {
      setNpcPositions(positions);
    }, []),
    200
  );

  // ── Mount Phaser ─────────────────────────────────────────────

  useEffect(() => {
    if (!containerRef.current || gameRef.current) return;

    const game = new Phaser.Game(createPhaserConfig(containerRef.current));
    gameRef.current = game;

    const onReady = () => {
      const scene = game.scene.getScene('WorldScene') as WorldScene;
      sceneRef.current = scene;
      setWorldMap(buildWorldMap());
      setReady(true);
    };

    const onInteract = (data: { type: any; roomId: string; npcId?: string }) => {
      openModal(data.type, data.roomId, data.npcId);
    };

    const onPlayerMove = () => {
      if (sceneRef.current) {
        throttledSetNpcPositions(sceneRef.current.getNpcPositions());
      }
    };

    const onSearch = () => setSearchOpen(true);

    game.events.on(WORLD_EVENTS.READY, onReady);
    game.events.on(WORLD_EVENTS.INTERACT, onInteract);
    game.events.on(WORLD_EVENTS.PLAYER_MOVE, onPlayerMove);
    game.events.on('world:search', onSearch);

    return () => {
      // Named removal — safe, does not nuke Phaser internal listeners
      game.events.off(WORLD_EVENTS.READY, onReady);
      game.events.off(WORLD_EVENTS.INTERACT, onInteract);
      game.events.off(WORLD_EVENTS.PLAYER_MOVE, onPlayerMove);
      game.events.off('world:search', onSearch);
      game.destroy(true);
      gameRef.current = null;
      sceneRef.current = null;
      setReady(false);
    };
  }, [openModal, throttledSetNpcPositions]);

  // ── Start API connections ─────────────────────────────────────

  useEffect(() => {
    startWorldApi();
    return () => stopWorldApi();
  }, []);

  // ── Global keyboard shortcuts ─────────────────────────────────

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        setSearchOpen((v) => !v);
      }
      if (e.key === 'Escape') setSearchOpen(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  // ── Teleport handlers ─────────────────────────────────────────

  const handleTeleportRoom = useCallback((roomId: string) => {
    sceneRef.current?.teleportToRoom(roomId);
    setSearchOpen(false);
  }, []);

  const handleTeleportNpc = useCallback((npcId: string) => {
    sceneRef.current?.teleportToNpc(npcId);
    setSearchOpen(false);
  }, []);

  const handleMinimapTeleport = useCallback((tx: number, ty: number) => {
    const roomId = closestRoomId(tx, ty);
    sceneRef.current?.teleportToRoom(roomId);
  }, []);

  // ── Render ───────────────────

  return (
    <div className="relative w-full h-full overflow-hidden bg-surface" ref={containerRef}>
      {ready && worldMap && (
        <>
          <WorldOverlay
            worldMap={worldMap}
            npcPositions={npcPositions}
            onMinimapTeleport={handleMinimapTeleport}
            colors={colors}
          />
          <ThemeToolbar />
          {searchOpen && (
            <SearchBar
              worldMap={worldMap}
              onTeleportRoom={handleTeleportRoom}
              onTeleportNpc={handleTeleportNpc}
              onClose={() => setSearchOpen(false)}
            />
          )}
          <InteractionModal />
        </>
      )}
      {!ready && (
        <div className="absolute inset-0 flex items-center justify-center bg-surface z-50">
          <div className="flex flex-col items-center gap-3">
            <div className="w-8 h-8 border-2 border-accent-blue/30 border-t-accent-blue rounded-full animate-spin" />
            <span className="text-xs text-text-muted font-mono tracking-wider">LOADING WORLD HQ…</span>
          </div>
        </div>
      )}
    </div>
  );
});
