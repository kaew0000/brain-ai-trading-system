// ============================================================
// Brain Bot V15 — Interaction Manager
// Handles E key interactions with NPCs and rooms,
// proximity detection, and React modal bridge.
// ============================================================

import Phaser from 'phaser';
import type { NPC } from './NPC';
import type { Player } from './Player';
import { ROOM_DEFINITIONS } from './Room';
import { getRoomAtTile } from './MapLoader';
import type { ModalType } from './types/world.types';
import { useWorldStore } from './worldStore';

type InteractCallback = (type: ModalType, roomId: string, npcId?: string) => void;
type RoomChangeCallback = (roomId: string | null) => void;

// ── Room interaction range (in tiles) ─────────────────────────────────────────
const ROOM_ENTER_RADIUS_SQ = (2 * 16) ** 2; // 2 tiles from room entrance

export class InteractionManager {
  private scene: Phaser.Scene;
  private npcs: NPC[];
  private player: Player;
  private eKey: Phaser.Input.Keyboard.Key;
  private onInteract: InteractCallback;
  private onRoomChange?: RoomChangeCallback;

  // Track which NPC is currently closets (for E-key action)
  private nearestNpc: NPC | null = null;
  private currentRoomId: string | null = null;

  // Debounce E press
  private eWasDown = false;

  // Room label display
  private roomLabel: Phaser.GameObjects.Text;
  private roomLabelTimer = 0;

  constructor(
    scene: Phaser.Scene,
    player: Player,
    npcs: NPC[],
    onInteract: InteractCallback,
    onRoomChange?: RoomChangeCallback,
  ) {
    this.scene = scene;
    this.player = player;
    this.npcs = npcs;
    this.onInteract = onInteract;
    this.onRoomChange = onRoomChange;

    this.eKey = scene.input.keyboard!.addKey(Phaser.Input.Keyboard.KeyCodes.E);

    // Room label (shown on room entry)
    this.roomLabel = scene.add.text(
      scene.cameras.main.width / 2,
      scene.cameras.main.height - 60,
      '',
      {
        fontSize: '11px',
        color: '#00ff88',
        fontFamily: 'monospace',
        backgroundColor: '#000000cc',
        padding: { x: 10, y: 4 },
      },
    );
    this.roomLabel.setScrollFactor(0); // fixed to camera
    this.roomLabel.setOrigin(0.5, 1);
    this.roomLabel.setDepth(100);
    this.roomLabel.setVisible(false);
  }

  update(delta: number): void {
    this.updateNpcProximity();
    this.updateRoomDetection();
    this.handleEKey();
    this.updateRoomLabel(delta);
  }

  // ── NPC proximity ─────────────────────────────────────────────

  private updateNpcProximity(): void {
    let nearest: NPC | null = null;
    let nearestDist = Infinity;

    for (const npc of this.npcs) {
      const dx = npc.x - this.player.x;
      const dy = npc.y - this.player.y;
      const distSq = dx * dx + dy * dy;

      const isNear = npc.isPlayerNearby(this.player.x, this.player.y);
      npc.showPrompt(isNear);

      if (isNear && distSq < nearestDist) {
        nearestDist = distSq;
        nearest = npc;
      }
    }

    this.nearestNpc = nearest;
  }

  // ── Room detection ────────────────────────────────────────────

  private updateRoomDetection(): void {
    const tx = this.player.tileX;
    const ty = this.player.tileY;
    const room = getRoomAtTile(tx, ty, ROOM_DEFINITIONS);
    const newRoomId = room?.id ?? null;

    if (newRoomId !== this.currentRoomId) {
      this.currentRoomId = newRoomId;
      if (room) {
        this.showRoomLabel(room.name);
      }
      // Fires camera zoom, interior lighting/audio swap, and a React
      // UI update event — the "doors work" behavior.
      this.onRoomChange?.(newRoomId);
    }
  }

  // ── E key handler ─────────────────────────────────────────────

  private handleEKey(): void {
    const eDown = this.eKey.isDown;

    if (eDown && !this.eWasDown) {
      // Interact with nearest NPC first
      if (this.nearestNpc) {
        const npc = this.nearestNpc;
        const room = ROOM_DEFINITIONS.find((r) => r.id === npc.def.roomId);
        if (room) {
          this.onInteract(room.modalType, room.id, npc.def.id);
          useWorldStore.getState().openModal(room.modalType, room.id, npc.def.id);
        }
        return;
      }

      // Otherwise, interact with the current room
      if (this.currentRoomId) {
        const room = ROOM_DEFINITIONS.find((r) => r.id === this.currentRoomId);
        if (room) {
          this.onInteract(room.modalType, room.id);
          useWorldStore.getState().openModal(room.modalType, room.id);
        }
      }
    }

    this.eWasDown = eDown;
  }

  // ── Room label ────────────────────────────────────────────────

  private showRoomLabel(name: string): void {
    this.roomLabel.setText(`▶ ${name}`);
    this.roomLabel.setVisible(true);
    this.roomLabel.setAlpha(1);
    this.roomLabelTimer = 2500; // show for 2.5 seconds
  }

  private updateRoomLabel(delta: number): void {
    if (this.roomLabelTimer > 0) {
      this.roomLabelTimer -= delta;
      if (this.roomLabelTimer <= 500) {
        // Fade out in last 500ms
        this.roomLabel.setAlpha(this.roomLabelTimer / 500);
      }
      if (this.roomLabelTimer <= 0) {
        this.roomLabel.setVisible(false);
      }
    }
  }

  // ── Teleport ──────────────────────────────────────────────────

  teleportToRoom(roomId: string): void {
    const room = ROOM_DEFINITIONS.find((r) => r.id === roomId);
    if (!room) return;
    const cx = room.tx + Math.floor(room.tw / 2);
    const cy = room.ty + Math.floor(room.th / 2);
    this.player.teleportTo(cx, cy);
    this.showRoomLabel(room.name);
    this.currentRoomId = room.id;
    this.onRoomChange?.(room.id);
    useWorldStore.getState().closeModal();
  }

  teleportToNpc(npcId: string): void {
    const npc = this.npcs.find((n) => n.def.id === npcId);
    if (!npc) return;
    const tx = Math.floor(npc.x / 16) + 2;
    const ty = Math.floor(npc.y / 16);
    this.player.teleportTo(tx, ty);
    useWorldStore.getState().closeModal();
  }

  getCurrentRoom(): string | null {
    return this.currentRoomId;
  }

  destroy(): void {
    this.roomLabel.destroy();
  }
}
