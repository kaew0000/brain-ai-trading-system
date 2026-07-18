// ============================================================
// Brain Bot V15 — WorldScene  (PNG-asset version)
// Main Phaser 3 scene. Assembles map, player, NPCs,
// camera, interactions, environment, and live data effects.
// All graphics loaded from PNG assets via AssetRegistry.
// React communicates via the PhaserBridge event emitter.
// ============================================================

import Phaser from 'phaser';
import { initAssets, getBuildingKeyForRoom } from './AssetLoader';
import { loadManifest } from '../../game/assets/AssetRegistry';
import { buildWorldMap, tileToPx, getRoomCenterPx, getRoomAtTile } from './MapLoader';
import { TILE_SIZE, ROOM_DEFINITIONS, NPC_DEFINITIONS, MAP_COLS, MAP_ROWS } from './Room';
import { Player } from './Player';
import { NPC } from './NPC';
import { CameraManager } from './CameraManager';
import { InteractionManager } from './InteractionManager';
import { useWorldStore, selectSystemSeverity, selectHasOpenPosition } from './worldStore';
import type { WorldMap, ModalType, WorldTheme } from './types/world.types';
import { buildTiledWorldMap, setWaterFrame, type BuiltTilemap } from './maps/TiledMapBuilder';
import { LightingSystem } from './lighting/LightingSystem';
import { DayNightCycle, type DayPhase } from './lighting/DayNightCycle';
import { ParticleEffects } from './effects/ParticleEffects';
import { MinimapCamera } from './ui/MinimapCamera';
import { setInteriorAmbience, setExteriorAmbience } from './AudioManager';

const WORLD_W = MAP_COLS * TILE_SIZE;
const WORLD_H = MAP_ROWS * TILE_SIZE;

// ── Events emitted to React via game.events ───────────────────────────────────
export const WORLD_EVENTS = {
  INTERACT:     'world:interact',
  PLAYER_MOVE:  'world:player_move',
  ROOM_ENTER:   'world:room_enter',
  READY:        'world:ready',
} as const;

// ── WorldScene ────────────────────────────────────────────────────────────────

export class WorldScene extends Phaser.Scene {
  // Core systems
  private worldMap!: WorldMap;
  private player!: Player;
  private npcs: NPC[] = [];
  private camera!: CameraManager;
  private interaction!: InteractionManager;

  // Rendering layers
  private tilemap!: BuiltTilemap;
  private layerEnv!: Phaser.GameObjects.Container;
  private layerFX!: Phaser.GameObjects.Container;

  // Animated world objects
  private fountainSprite: Phaser.GameObjects.Image | null = null;
  private envLights: Phaser.GameObjects.Arc[] = [];
  private blinkLeds: { obj: Phaser.GameObjects.Arc; timer: number; interval: number }[] = [];
  private serverFlash: Phaser.GameObjects.Rectangle | null = null;

  // Lighting / day-night / particles / minimap
  private lighting!: LightingSystem;
  private dayNight!: DayNightCycle;
  private particles!: ParticleEffects;
  private minimap!: MinimapCamera;
  private currentDayPhase: DayPhase = 'day';

  // Room the player is currently standing inside (for zoom/light/audio)
  private playerRoomId: string | null = null;

  // Ambient overlay for night / emergency mode
  private ambientOverlay!: Phaser.GameObjects.Rectangle;
  private exteriorDarknessOverlay!: Phaser.GameObjects.Rectangle;

  // Animation time accumulators
  private animTimer = 0;
  private waterFrame = 0;
  private fountainFrame = 0;

  // Global alert flash
  private alertFlashTimer = 0;
  private alertFlashOn = false;

  // Theme
  private currentTheme: WorldTheme = 'cyberpunk';

  constructor() {
    super({ key: 'WorldScene' });
  }

  // ── Lifecycle ──────────────────────────────────────────────────

  /** init() runs before preload(); we use it to fetch the manifest async. */
  init(): void {
    // Trigger manifest fetch early — preload() queues the actual file loads
    loadManifest().catch((e) =>
      console.error('WorldScene: manifest load failed —', e),
    );
  }

  preload(): void {
    // initAssets() is awaited via the scene's load event chain:
    // we call it synchronously here (it registers Phaser load.image calls).
    // The async manifest fetch resolves before preload because init() already
    // fired it; if it hasn't resolved yet the loader will still queue correctly
    // once the manifest arrives, since Phaser's loader runs after preload().
    initAssets(this).catch((e) =>
      console.error('WorldScene: initAssets failed —', e),
    );
  }

  create(): void {
    // Build tile map
    this.worldMap = buildWorldMap();

    // Set world physics bounds
    this.physics.world.setBounds(0, 0, WORLD_W, WORLD_H);

    // Real Phaser Tilemap — Ground/Road/Water/Collision layers built from
    // a genuine Tiled-JSON document + a runtime-packed tileset atlas.
    // Replaces the old RenderTexture/individual-image background.
    this.tilemap = buildTiledWorldMap(this, this.worldMap);

    // Lighting (Phaser Lights2D) — ground/road/water layers opt in so
    // they respond to point lights and the day/night ambient color.
    this.lighting = new LightingSystem(this);
    this.lighting.makeLit(this.tilemap.groundLayer);
    this.lighting.makeLit(this.tilemap.roadLayer);
    this.lighting.makeLit(this.tilemap.waterLayer);

    // Particle FX layer
    this.particles = new ParticleEffects(this);

    // Environment layer (trees, lamps, props, buildings)
    this.layerEnv = this.add.container(0, 0);
    this.layerEnv.setDepth(5);
    this.buildEnvironment();

    // FX layer (particles, glows)
    this.layerFX = this.add.container(0, 0);
    this.layerFX.setDepth(8);

    // Place player at Central Plaza entrance
    this.player = new Player(this, this.worldMap, 50, 28);
    this.lighting.makeLit(this.player.getSprite());

    // Spawn NPCs
    for (const def of NPC_DEFINITIONS) {
      const npc = new NPC(this, this.worldMap, def);
      this.npcs.push(npc);
      this.lighting.makeLit(npc.getSprite());
    }

    // Camera
    this.camera = new CameraManager(this, this.player);

    // Interaction — now also drives camera zoom + interior lighting/audio
    // whenever the player crosses a room boundary (door).
    this.interaction = new InteractionManager(
      this, this.player, this.npcs,
      (type, roomId, npcId) => {
        this.game.events.emit(WORLD_EVENTS.INTERACT, { type, roomId, npcId });
      },
      (roomId) => this.onPlayerRoomChanged(roomId),
    );

    // Day/night cycle — drives ambient light + exterior darkness overlay.
    this.dayNight = new DayNightCycle(this.lighting, 8 * 60 * 1000, (phase) => {
      this.currentDayPhase = phase;
      this.game.events.emit('world:day_phase', phase);
    });

    // Exterior darkness overlay (skipped while indoors — interiors stay lit
    // by their own point lights regardless of time of day).
    this.exteriorDarknessOverlay = this.add.rectangle(0, 0, WORLD_W, WORLD_H, 0x000020, 0);
    this.exteriorDarknessOverlay.setOrigin(0, 0);
    this.exteriorDarknessOverlay.setDepth(48);
    this.exteriorDarknessOverlay.setBlendMode(Phaser.BlendModes.MULTIPLY);

    // Ambient overlay (for themes / alert state)
    this.ambientOverlay = this.add.rectangle(0, 0, WORLD_W, WORLD_H, 0x000000, 0);
    this.ambientOverlay.setOrigin(0, 0);
    this.ambientOverlay.setDepth(50);

    // Real minimap camera — renders the actual world, not flat colors.
    this.minimap = new MinimapCamera(
      this,
      (tx, ty) => this.teleportPlayerToTile(tx, ty),
      [this.ambientOverlay, this.exteriorDarknessOverlay],
    );

    // Ambient scene lights: street lamps, fountain, teleport hub, server room
    this.buildAmbientLights();

    // Subscribe to store changes that affect the world
    this.setupStoreSubscriptions();

    // Room labels
    this.buildRoomLabels();

    // Keyboard Ctrl+K — search (emit to React)
    const ctrlKey = this.input.keyboard!.addKey(Phaser.Input.Keyboard.KeyCodes.CTRL);
    const kKey    = this.input.keyboard!.addKey(Phaser.Input.Keyboard.KeyCodes.K);
    ctrlKey.on('down', () => {
      if (kKey.isDown) this.game.events.emit('world:search');
    });
    kKey.on('down', () => {
      if (this.input.keyboard!.checkDown(ctrlKey, 0)) {
        this.game.events.emit('world:search');
      }
    });

    // Escape key — close modal
    this.input.keyboard!.addKey(Phaser.Input.Keyboard.KeyCodes.ESC).on('down', () => {
      useWorldStore.getState().closeModal();
    });

    // Signal ready
    this.game.events.emit(WORLD_EVENTS.READY);
  }

  update(_time: number, delta: number): void {
    // NPC updates
    for (const npc of this.npcs) npc.update(delta);

    // Player update
    this.player.update(delta);

    // Camera update
    this.camera.update(delta);

    // Interaction update
    this.interaction.update(delta);

    // World animations
    this.animTimer += delta;

    // Water animation (every 400ms, matching WORLD_CONFIG.waterFrameMs) —
    // now swaps the real Water TilemapLayer's tile indices, not loose sprites.
    if (this.animTimer > 400) {
      this.animTimer = 0;
      this.waterFrame = (this.waterFrame + 1) % 9;
      setWaterFrame(this.tilemap, this.waterFrame);
      this.fountainFrame = (this.fountainFrame + 1) % 3;
      if (this.fountainSprite) {
        // Cycle through hologram_a/b/c for fountain animation
        const hologramKeys = ['deco__hologram_a', 'deco__hologram_b', 'deco__hologram_c'];
        this.fountainSprite.setTexture(hologramKeys[this.fountainFrame] ?? hologramKeys[0]);
      }
    }

    // Lighting flicker + day/night cycle
    this.lighting.update(delta);
    const { overlayAlpha } = this.dayNight.update(delta);
    // Exterior darkens with time of day; fades out while the player is
    // indoors so interiors read as consistently lit by their own lights.
    const indoors = this.playerRoomId !== null && this.playerRoomId !== 'plaza';
    this.exteriorDarknessOverlay.setAlpha(indoors ? 0 : overlayAlpha);

    // Minimap
    this.minimap.update(
      this.player.x, this.player.y,
      this.npcs.map((n) => ({
        id: n.def.id, x: n.x, y: n.y,
        accent: n.def.bodyColor,
      })),
    );

    // LED blinks
    for (const led of this.blinkLeds) {
      led.timer -= delta;
      if (led.timer <= 0) {
        led.timer = led.interval + Math.random() * 200;
        led.obj.setVisible(!led.obj.visible);
      }
    }

    // Global alert flash (WebSocket disconnected or system critical)
    const severity = selectSystemSeverity(useWorldStore.getState());
    if (severity === 'critical') {
      this.alertFlashTimer -= delta;
      if (this.alertFlashTimer <= 0) {
        this.alertFlashTimer = 800;
        this.alertFlashOn = !this.alertFlashOn;
        this.ambientOverlay.setFillStyle(0xff0000, this.alertFlashOn ? 0.06 : 0);
        if (this.serverFlash) {
          this.serverFlash.setFillStyle(
            this.alertFlashOn ? 0xff0000 : 0x000000,
            this.alertFlashOn ? 0.4 : 0,
          );
        }
      }
    } else if (severity === 'warn') {
      this.ambientOverlay.setFillStyle(0xff8800, 0.02);
      if (this.serverFlash) this.serverFlash.setFillStyle(0xff8800, 0.15);
    } else {
      this.ambientOverlay.setAlpha(0);
      if (this.serverFlash) this.serverFlash.setAlpha(0);
    }

    // Player position → React
    this.game.events.emit(WORLD_EVENTS.PLAYER_MOVE, {
      tx: this.player.tileX,
      ty: this.player.tileY,
    });
  }

  // ── Ambient lights / room transitions / minimap teleport ────────

  /** Point lights for lamps, the plaza fountain, teleport hub, server room. */
  private buildAmbientLights(): void {
    if (!this.lighting.isEnabled) return;

    const lampPositions: Array<[number, number]> = [
      [20, 17], [36, 17], [60, 17], [74, 17],
      [20, 36], [50, 36], [74, 36],
      [20, 54], [50, 54], [82, 54],
      [10, 27], [10, 46],
    ];
    for (const [tx, ty] of lampPositions) {
      const { x, y } = tileToPx(tx, ty);
      this.lighting.addLight(x, y - 4, TILE_SIZE * 4, 0xffee88, 1.1, { speed: 0.006, amount: 0.15 });
    }

    const plaza = ROOM_DEFINITIONS.find((r) => r.id === 'plaza')!;
    const { x: px, y: py } = getRoomCenterPx(plaza);
    this.lighting.addLight(px, py - TILE_SIZE * 2, TILE_SIZE * 6, 0x66ddff, 1.4, { speed: 0.01, amount: 0.1 });
    this.particles.addFountainMist(px, py - TILE_SIZE * 2);

    const teleport = ROOM_DEFINITIONS.find((r) => r.id === 'teleport')!;
    const { x: tpx, y: tpy } = getRoomCenterPx(teleport);
    this.lighting.addLight(tpx, tpy, TILE_SIZE * 4, 0x00ffff, 1.5, { speed: 0.02, amount: 0.2 });
    this.particles.addPortalSparkle(tpx, tpy, 0x00ffff);

    const server = ROOM_DEFINITIONS.find((r) => r.id === 'server')!;
    const { x: spx, y: spy } = getRoomCenterPx(server);
    this.lighting.addLight(spx, spy, TILE_SIZE * 5, 0x22ff44, 1.0);
    this.particles.addServerSparks(spx, spy);

    // One softly lit point per room (interior fill light near the door)
    for (const room of ROOM_DEFINITIONS) {
      if (room.id === 'plaza' || room.id === 'teleport' || room.id === 'server') continue;
      const { x, y } = getRoomCenterPx(room);
      this.lighting.addLight(x, y, Math.max(room.tw, room.th) * TILE_SIZE * 0.9, room.accentColor, 0.9);
    }
  }

  /**
   * Called by InteractionManager whenever the player's room changes
   * (i.e. walks through a door). Drives camera zoom-in on entering a
   * building interior, zoom-out in the open plaza/outdoors, and swaps
   * the procedural audio ambience + notifies React for UI updates.
   */
  private onPlayerRoomChanged(roomId: string | null): void {
    this.playerRoomId = roomId;
    const isOutdoor = roomId === null || roomId === 'plaza';

    if (isOutdoor) {
      this.camera.setInteriorZoom(false);
      setExteriorAmbience();
    } else {
      this.camera.setInteriorZoom(true);
      const room = ROOM_DEFINITIONS.find((r) => r.id === roomId);
      setInteriorAmbience(room?.id ?? 'default');
    }

    this.game.events.emit(WORLD_EVENTS.ROOM_ENTER, { roomId });
  }

  /** Used by the minimap camera's click-to-teleport. */
  private teleportPlayerToTile(tx: number, ty: number): void {
    if (!this.isTileTeleportable(tx, ty)) return;
    this.player.teleportTo(tx, ty);
    const room = getRoomAtTile(tx, ty, ROOM_DEFINITIONS);
    this.onPlayerRoomChanged(room?.id ?? null);
  }

  private isTileTeleportable(tx: number, ty: number): boolean {
    if (tx < 0 || tx >= MAP_COLS || ty < 0 || ty >= MAP_ROWS) return false;
    const tile = this.worldMap.tiles[ty]?.[tx];
    return tile !== 'wall' && tile !== 'water' && tile !== 'void';
  }

  // ── Environment (trees, lamps, props, buildings) ───────────────

  private buildEnvironment(): void {
    const TILE_SCALE = 1 / 8; // PNG tiles are ~125px wide → render at TILE_SIZE=16

    // ── Buildings: place PNG above each room's entry wall ──────────
    for (const room of ROOM_DEFINITIONS) {
      if (room.id === 'plaza' || room.id === 'teleport') continue;
      const bKey = getBuildingKeyForRoom(this, room.id);
      if (!this.textures.exists(bKey)) continue;

      const cx = (room.tx + room.tw / 2) * TILE_SIZE;
      const cy = room.ty * TILE_SIZE;
      const bImg = this.add.image(cx, cy, bKey);
      // Scale building to span the room width, max height = room height
      const srcW = this.textures.get(bKey).getSourceImage().width || 1;
      const srcH = this.textures.get(bKey).getSourceImage().height || 1;
      const maxW  = room.tw * TILE_SIZE * 0.9;
      const maxH  = room.th * TILE_SIZE * 0.6;
      const scale = Math.min(maxW / srcW, maxH / srcH);
      bImg.setScale(scale);
      bImg.setOrigin(0.5, 1.0); // anchor to bottom-center
      bImg.setDepth(3 + room.ty * 0.001);
      this.layerEnv.add(bImg);
    }

    // ── Trees scattered in grass areas ────────────────────────────
    const treePositions = this.sampleGrassPositions(60, 4);
    for (const [tx, ty] of treePositions) {
      const { x, y } = tileToPx(tx, ty);
      // Alternate tree sizes
      const sizeKey = Math.random() < 0.5 ? 'tile__tree_large' : 'tile__tree_medium';
      const key = this.textures.exists(sizeKey) ? sizeKey : 'tile__grass_plain';
      const tree = this.add.image(x, y - TILE_SIZE / 2, key);
      const srcW = this.textures.get(key).getSourceImage().width || 1;
      tree.setScale(Math.min((TILE_SIZE * 2) / srcW, 1));
      tree.setDepth(6 + ty * 0.001);
      this.layerEnv.add(tree);
    }

    // ── Street lamps at path intersections ────────────────────────
    const lampPositions: Array<[number, number]> = [
      [20, 17], [36, 17], [60, 17], [74, 17],
      [20, 36], [50, 36], [74, 36],
      [20, 54], [50, 54], [82, 54],
      [10, 27], [10, 46],
    ];
    const lampKey = this.textures.exists('deco__street_lamp_a')
      ? 'deco__street_lamp_a' : 'tile__grass_plain';
    for (const [tx, ty] of lampPositions) {
      const { x, y } = tileToPx(tx, ty);
      const lamp = this.add.image(x, y - 4, lampKey);
      const srcW = this.textures.get(lampKey).getSourceImage().width || 1;
      lamp.setScale(Math.min((TILE_SIZE * 1.5) / srcW, 1));
      lamp.setDepth(7);
      this.layerEnv.add(lamp);

      const glow = this.add.arc(x, y + 2, TILE_SIZE * 2.5, 0, 360, false, 0xffee88, 0.06);
      glow.setDepth(3);
      this.envLights.push(glow);
    }

    // ── Flowers in garden areas ───────────────────────────────────
    const flowerPositions = this.sampleGrassPositions(30, 3);
    const flowerKeys = ['deco__flower_a','deco__flower_b','deco__flower_c'].filter(
      k => this.textures.exists(k),
    );
    for (const [tx, ty] of flowerPositions) {
      const { x, y } = tileToPx(tx, ty);
      const fKey = flowerKeys.length
        ? flowerKeys[Math.floor(Math.random() * flowerKeys.length)]
        : 'tile__grass_plain';
      const flower = this.add.image(x, y, fKey);
      const srcW = this.textures.get(fKey).getSourceImage().width || 1;
      flower.setScale(Math.min(TILE_SIZE / srcW, 1));
      flower.setDepth(4);
      this.layerEnv.add(flower);
    }

    // ── Computers inside rooms ────────────────────────────────────
    const compKey = this.textures.exists('prop__terminal_a')
      ? 'prop__terminal_a' : 'tile__floor_tech_plain';
    for (const room of ROOM_DEFINITIONS) {
      if (room.id === 'plaza' || room.id === 'teleport') continue;
      for (let i = 0; i < 2; i++) {
        const cx = room.tx + 2 + i * 4;
        const cy = room.ty + 2;
        const { x, y } = tileToPx(cx, cy);
        const comp = this.add.image(x, y, compKey);
        const srcW = this.textures.get(compKey).getSourceImage().width || 1;
        comp.setScale(Math.min(TILE_SIZE / srcW, 1));
        comp.setDepth(8);
        this.layerEnv.add(comp);

        const led = this.add.arc(x + 6, y - 4, 1.5, 0, 360, false, 0x00ff44, 1);
        led.setDepth(9);
        this.blinkLeds.push({ obj: led, timer: Math.random() * 1000, interval: 500 + Math.random() * 1500 });
      }
    }

    // ── Server racks in Server Room ───────────────────────────────
    const serverRoom = ROOM_DEFINITIONS.find((r) => r.id === 'server')!;
    const rackKey = this.textures.exists('prop__server_rack_lg')
      ? 'prop__server_rack_lg' : 'tile__floor_tech_plain';
    for (let i = 0; i < 4; i++) {
      const { x, y } = tileToPx(serverRoom.tx + 2 + i * 3, serverRoom.ty + 2);
      const rack = this.add.image(x, y, rackKey);
      const srcW = this.textures.get(rackKey).getSourceImage().width || 1;
      rack.setScale(Math.min((TILE_SIZE * 2) / srcW, 1));
      rack.setDepth(8);
      this.layerEnv.add(rack);
    }

    // ── Fountain in Central Plaza ─────────────────────────────────
    const plazaRoom = ROOM_DEFINITIONS.find((r) => r.id === 'plaza')!;
    const plazaCx = plazaRoom.tx + Math.floor(plazaRoom.tw / 2);
    const plazaCy = plazaRoom.ty + Math.floor(plazaRoom.th / 2);
    const { x: fx, y: fy } = tileToPx(plazaCx, plazaCy - 2);
    const fountainKey = this.textures.exists('tile__fountain_large')
      ? 'tile__fountain_large' : 'tile__grass_plain';
    this.fountainSprite = this.add.image(fx, fy, fountainKey);
    const fSrcW = this.textures.get(fountainKey).getSourceImage().width || 1;
    this.fountainSprite.setScale(Math.min((TILE_SIZE * 3) / fSrcW, 1));
    this.fountainSprite.setDepth(7);

    // ── Server flash overlay ──────────────────────────────────────
    this.serverFlash = this.add.rectangle(
      serverRoom.tx * TILE_SIZE, serverRoom.ty * TILE_SIZE,
      serverRoom.tw * TILE_SIZE, serverRoom.th * TILE_SIZE,
      0xff0000, 0,
    );
    this.serverFlash.setOrigin(0, 0);
    this.serverFlash.setDepth(49);
  }

  // ── Room labels ────────────────────────────────────────────────

  private buildRoomLabels(): void {
    for (const room of ROOM_DEFINITIONS) {
      const cx = (room.tx + room.tw / 2) * TILE_SIZE;
      const cy = (room.ty + 1.5) * TILE_SIZE;

      const label = this.add.text(cx, cy, room.name.toUpperCase(), {
        fontSize: '6px',
        color: room.labelColor,
        fontFamily: 'monospace',
        fontStyle: 'bold',
        stroke: '#000000',
        strokeThickness: 2,
      });
      label.setOrigin(0.5, 0);
      label.setDepth(15);

      const padX = 5, padY = 2;
      const plateW = label.width + padX * 2;
      const plateH = label.height + padY * 2;
      const plate = this.add.graphics();
      plate.fillStyle(0x05050c, 0.78);
      plate.fillRoundedRect(cx - plateW / 2, cy - padY, plateW, plateH, 2);
      plate.lineStyle(1, room.accentColor, 0.8);
      plate.strokeRoundedRect(cx - plateW / 2, cy - padY, plateW, plateH, 2);
      plate.fillStyle(room.accentColor, 0.9);
      plate.fillRect(cx - plateW / 2 + 1, cy - padY + 1, 1, 1);
      plate.fillRect(cx + plateW / 2 - 2, cy - padY + 1, 1, 1);
      plate.setDepth(14);
      label.setDepth(15);
    }
  }

  // ── Store subscriptions ────────────────────────────────────────

  private setupStoreSubscriptions(): void {
    useWorldStore.subscribe(
      (s) => s.theme,
      (theme) => this.applyTheme(theme),
    );
    useWorldStore.subscribe(
      (s) => s.wsConnected,
      (connected) => {
        if (!connected) this.cameras.main.shake(300, 0.003);
      },
    );
  }

  private applyTheme(theme: WorldTheme): void {
    this.currentTheme = theme;
    switch (theme) {
      case 'cyberpunk': this.cameras.main.setBackgroundColor('#070714'); break;
      case 'retro':     this.cameras.main.setBackgroundColor('#001400'); break;
      case 'light':     this.cameras.main.setBackgroundColor('#c8d8f0'); break;
      default:          this.cameras.main.setBackgroundColor('#0d1117');
    }
  }

  // ── Public bridge methods ──────────────────────────────────────

  teleportToRoom(roomId: string): void {
    this.interaction.teleportToRoom(roomId);
    const room = ROOM_DEFINITIONS.find((r) => r.id === roomId);
    if (room) {
      const { x, y } = getRoomCenterPx(room);
      this.camera.panToPosition(x, y);
    }
  }

  teleportToNpc(npcId: string): void {
    this.interaction.teleportToNpc(npcId);
    const npc = this.npcs.find((n) => n.def.id === npcId);
    if (npc) this.camera.panToPosition(npc.x, npc.y);
  }

  getNpcPositions(): Array<{ id: string; tx: number; ty: number }> {
    return this.npcs.map((n) => ({
      id: n.def.id,
      tx: Math.floor(n.x / TILE_SIZE),
      ty: Math.floor(n.y / TILE_SIZE),
    }));
  }

  // ── Helpers ────────────────────────────────────────────────────

  private sampleGrassPositions(count: number, minDist: number): Array<[number, number]> {
    const positions: Array<[number, number]> = [];
    const maxAttempts = count * 20;
    let attempts = 0;
    while (positions.length < count && attempts < maxAttempts) {
      attempts++;
      const tx = 2 + Math.floor(Math.random() * (MAP_COLS - 4));
      const ty = 2 + Math.floor(Math.random() * (MAP_ROWS - 4));
      if (this.worldMap.tiles[ty]?.[tx] !== 'grass') continue;
      const tooClose = positions.some(([ox, oy]) => {
        const dx = ox - tx; const dy = oy - ty;
        return Math.sqrt(dx * dx + dy * dy) < minDist;
      });
      if (!tooClose) positions.push([tx, ty]);
    }
    return positions;
  }
}
