// ============================================================
// Brain Bot V15 — World HQ Page
// Root React component for the 2D pixel-art trading HQ.
// Mounts Phaser, bridges events to React overlays, manages
// the full module lifecycle cleanly.
// ============================================================

import { useEffect, useRef, useState, useCallback } from 'react';
import Phaser from 'phaser';
import { WorldScene, WORLD_EVENTS } from './WorldScene';
import { startWorldApi, stopWorldApi } from './worldApi';
import { useWorldStore, THEME_COLORS } from './worldStore';
import { buildWorldMap } from './MapLoader';
import { ROOM_DEFINITIONS } from './Room';
import type { WorldMap } from './types/world.types';

import WorldOverlay from './components/WorldOverlay';
import SearchBar from './components/SearchBar';
import ThemeToolbar from './components/ThemeToolbar';
import InteractionModal from './components/InteractionModal';

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Find the closest room to a given tile coordinate */
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

// ── Phaser game factory ────────────────────────────────────────────────────────

function createPhaserConfig(parent: HTMLElement): Phaser.Types.Core.GameConfig {
  return {
    type: Phaser.AUTO,
    parent,
    width:  '100%',
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

export default function WorldPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const gameRef      = useRef<Phaser.Game | null>(null);
  const sceneRef     = useRef<WorldScene | null>(null);

  const [worldMap, setWorldMap]         = useState<WorldMap | null>(null);
  const [npcPositions, setNpcPositions] = useState<Array<{ id: string; tx: number; ty: number }>>([]);
  const [searchOpen, setSearchOpen]     = useState(false);
  const [ready, setReady]               = useState(false);

  const { theme, openModal } = useWorldStore();
  const colors = THEME_COLORS[theme];

  // ── Mount Phaser ─────────────────────────────────────────────

  useEffect(() => {
    if (!containerRef.current || gameRef.current) return;

    const game = new Phaser.Game(createPhaserConfig(containerRef.current));
    gameRef.current = game;

    game.events.on(WORLD_EVENTS.READY, () => {
      const scene = game.scene.getScene('WorldScene') as WorldScene;
      sceneRef.current = scene;
      setWorldMap(buildWorldMap());
      setReady(true);
    });

    game.events.on(
      WORLD_EVENTS.INTERACT,
      (data: { type: any; roomId: string; npcId?: string }) => {
        openModal(data.type, data.roomId, data.npcId);
      },
    );

    // NPC positions updated every tile-move
    game.events.on(WORLD_EVENTS.PLAYER_MOVE, () => {
      if (sceneRef.current) {
        setNpcPositions(sceneRef.current.getNpcPositions());
      }
    });

    // Ctrl+K from Phaser keyboard
    game.events.on('world:search', () => setSearchOpen(true));

    return () => {
      game.events.removeAllListeners();
      game.destroy(true);
      gameRef.current = null;
      sceneRef.current = null;
      setReady(false);
    };
  }, [openModal]);

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

  // ── Render ────────────────────────────────────────────────────

  return (
    <div style={{
      position: 'relative',
      width: '100%',
      height: '100vh',
      overflow: 'hidden',
      background: colors.bg,
      userSelect: 'none',
    }}>
      {/* ── Phaser canvas ── */}
      <div
        ref={containerRef}
        id="world-hq-canvas"
        style={{ position: 'absolute', inset: 0, zIndex: 0 }}
      />

      {/* ── Loading screen ── */}
      {!ready && <LoadingScreen colors={colors} />}

      {/* ── React overlays (only after Phaser is ready) ── */}
      {ready && (
        <>
          {/*
            NOTE: the minimap used to be a separate React <canvas> that drew
            flat color rectangles for rooms. It's now a real second Phaser
            camera (see ui/MinimapCamera.ts) that renders the actual world
            geometry/sprites in the top-right corner of the game canvas
            itself, and handles its own click-to-teleport input directly
            in WorldScene — so there's nothing to mount here anymore.
          */}

          <WorldOverlay />

          <ThemeToolbar onSearch={() => setSearchOpen(true)} />

          <InteractionModal onTeleport={handleTeleportRoom} />

          <SearchBar
            open={searchOpen}
            onClose={() => setSearchOpen(false)}
            onTeleportRoom={handleTeleportRoom}
            onTeleportNpc={handleTeleportNpc}
          />
        </>
      )}
    </div>
  );
}

// ── LoadingScreen ─────────────────────────────────────────────────────────────

function LoadingScreen({ colors }: { colors: any }) {
  return (
    <div style={{
      position: 'absolute', inset: 0,
      background: '#070714',
      display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      zIndex: 500, fontFamily: 'monospace',
    }}>
      <style>{`
        @keyframes hq-scan {
          0%   { left: 0%;  width: 30%; }
          50%  { left: 70%; width: 30%; }
          100% { left: 0%;  width: 30%; }
        }
        @keyframes hq-blink { 0%,100%{opacity:1} 50%{opacity:0.3} }
      `}</style>

      {/* Brain icon pulse */}
      <div style={{ fontSize: 40, marginBottom: 16, animation: 'hq-blink 1.8s ease-in-out infinite' }}>
        🧠
      </div>

      <div style={{
        color: '#00ff88', fontSize: 13, letterSpacing: 4,
        marginBottom: 4, textTransform: 'uppercase',
      }}>
        Brain Bot V15
      </div>
      <div style={{ color: '#ffd700', fontSize: 10, letterSpacing: 2, marginBottom: 32 }}>
        Command World — Loading
      </div>

      {/* Progress bar */}
      <div style={{
        width: 200, height: 4, background: '#111',
        borderRadius: 2, overflow: 'hidden', position: 'relative',
        border: '1px solid #1a1a3e',
      }}>
        <div style={{
          position: 'absolute', height: '100%',
          background: '#00ff88', borderRadius: 2,
          animation: 'hq-scan 1.6s ease-in-out infinite',
        }} />
      </div>

      <div style={{ color: '#333', fontSize: 8, marginTop: 24, letterSpacing: 1 }}>
        GENERATING PIXEL WORLD · CONNECTING AGENTS
      </div>

      {/* Boot messages */}
      <div style={{
        marginTop: 32, textAlign: 'left', width: 260,
        color: '#1a4a1a', fontSize: 8, lineHeight: 2,
      }}>
        {[
          'Initializing Phaser 3 renderer…',
          'Generating procedural tile map…',
          'Spawning 10 AI agents…',
          'Connecting WebSocket streams…',
          'Loading trading data…',
        ].map((msg, i) => (
          <div key={i} style={{
            color: '#1a5a1a',
            animation: `hq-blink ${1 + i * 0.2}s ease-in-out infinite`,
            animationDelay: `${i * 0.3}s`,
          }}>
            ▶ {msg}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Audio integration note ─────────────────────────────────────
// Import and initialize AudioManager in the mount useEffect:
//
//   import { initAudio, destroyAudio, playModalOpen, playTeleport } from './AudioManager';
//
//   // Inside mount useEffect:
//   initAudio();
//   return () => { destroyAudio(); ... }
//
//   // On teleport:
//   playTeleport();
//
//   // On modal open:
//   playModalOpen();
