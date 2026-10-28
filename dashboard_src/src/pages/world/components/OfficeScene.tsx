// dashboard_src/src/pages/world/components/OfficeScene.tsx
// Phase W10 (shapes) -> Phase W11-follow-up (real art). Consumes Phase
// W8's RenderFrame wire format directly. Real PNG assets now exist
// (dashboard_src/public/assets/world/) and AssetRegistry.ts can load
// them, but RenderCommand.assetId (backend, world/data/assets/
// asset_manifest.json ids like "furniture.desk") and the frontend
// manifest's keys ("desk_single") are two vocabularies that were never
// connected — see ../assetMapping.ts for the translation tables and
// the full root-cause writeup. Every position, color, and label still
// comes from the real RenderFrame; only *how* each command is drawn
// changed. Anything with no mapping (see assetMapping.ts's comments on
// what was deliberately left out) falls back to AssetRegistry's own
// coloured-placeholder texture — never a crash, never silently blank.

import Phaser from 'phaser'
import { useEffect, useRef } from 'react'
import type { RenderFrame } from '../types'
import { assetDisplayName, BEHAVIOR_COLORS, characterTweenOffset, frameSignature, isIsometric, isoDepth, isoDiamondPoints } from '../sceneMapping'
import { WORLD_CONFIG } from '../../../game/config/world.config'
import { CHARACTER_TO_ROLE, DISTRICT_TO_BUILDING, resolvePropAssetId } from '../assetMapping'
import { getBuilding, getDecoration, getIsoNPC, getIsoProp, getIsoTile, getIsoWalk, getManifest, getNPC, getNPCFrame, getProp, loadManifest, registerAssets } from '../../../game/assets/AssetRegistry'
import type { IsoManifest } from '../isoAssets'
import { hasIsoCharacter, isoDirectionFromDelta, isoFloorTileKey, isoFloorTileLayout, isoPoseFrame, isoPoseName, isoPropDepthOffset, isoPropOrigin, isoWalkFrame, resolveIsoProp } from '../isoAssets'

const FURNITURE_SIZE = 32 // px — matches the footprint the old 28x28 rectangle occupied
const CHARACTER_DISPLAY_HEIGHT = 40 // px — matches the visual weight of the old 14px-radius circle
const ISO_CHARACTER_DISPLAY_HEIGHT = 56 // px — iso pose frames are taller (64x96) than the legacy 140x160 sheets at 40px
const ISO_FLOOR_HALF_WIDTH = 320 // px — half of the 640px floor image footprint; diamond keeps the same width
const ISO_FLOOR_FILL = 0x1e293b
const ISO_FLOOR_EDGE = 0x475569

class OfficeCanvasScene extends Phaser.Scene {
  private frame: RenderFrame | null = null
  private layer?: Phaser.GameObjects.Container
  // Live view (V16 §82): last drawn frame identity (skip no-op redraws), the room it
  // belonged to, and each character's sprite so a redraw can start from where it is now.
  private lastSignature: string | null = null
  private lastDrawnRoomId: string | null = null
  private characterSprites = new Map<string, Phaser.GameObjects.Image | Phaser.GameObjects.Sprite>()

  constructor() {
    super('OfficeCanvasScene')
  }

  preload(): void {
    // Requires loadManifest() to have already resolved — see the React
    // wrapper below, which awaits it before this Scene is even created.
    registerAssets(this)
  }

  create(): void {
    this.layer = this.add.container(0, 0)
    this.cameras.main.setBackgroundColor('#0f172a')
    if (this.frame) this.draw(this.frame)
  }

  /** Called by the React wrapper whenever a new RenderFrame arrives. */
  setFrame(frame: RenderFrame): void {
    const signature = frameSignature(frame)
    const unchanged = this.frame !== null && signature === this.lastSignature
    this.frame = frame
    this.lastSignature = signature
    if (unchanged) return // same picture: keep the current sprites (and any glide in progress)
    if (this.layer) this.draw(frame)
  }

  /** Slides display objects from (their position + dx, + dy) back to where they were created. */
  private glide(
    objects: (Phaser.GameObjects.GameObject & { x: number; y: number })[],
    dx: number,
    dy: number,
    onComplete?: () => void,
  ): void {
    objects.forEach((obj, index) => {
      const toX = obj.x
      const toY = obj.y
      obj.x = toX + dx
      obj.y = toY + dy
      // All tweens share one duration, so the last one finishing means the whole glide is done.
      const done = index === objects.length - 1 ? onComplete : undefined
      this.tweens.add({ targets: obj, x: toX, y: toY, duration: WORLD_CONFIG.characterTweenMs, ease: 'Linear', onComplete: done })
    })
  }

  /**
   * Starts the 4-direction walk cycle for a sprite that is gliding by (-dx,-dy) -> (0,0). Returns a callback that
   * puts the sprite back on its pose frame, or null when this character has no walk sheet (caller just glides).
   */
  private startWalk(
    sprite: Phaser.GameObjects.Sprite,
    characterId: string,
    manifest: IsoManifest,
    dx: number,
    dy: number,
    poseTexture: string,
    poseFrame: number,
  ): (() => void) | null {
    const walkKey = getIsoWalk(this, characterId)
    const direction = isoDirectionFromDelta(-dx, -dy)
    const frame = isoWalkFrame(manifest, characterId, direction, 0)
    if (!walkKey || !frame || !manifest.walk) return null
    const animKey = `iso_walk__${characterId}__${direction}`
    if (!this.anims.exists(animKey)) {
      const start = frame.row * manifest.walk.frames
      this.anims.create({
        key: animKey,
        frames: this.anims.generateFrameNumbers(walkKey, { start, end: start + manifest.walk.frames - 1 }),
        frameRate: manifest.walk.fps,
        repeat: -1,
      })
    }
    sprite.play(animKey)
    return () => {
      if (!sprite.active) return // redraw already destroyed it
      sprite.stop()
      sprite.setTexture(poseTexture, poseFrame)
    }
  }

  /** Draws one isometric prop (manifest-driven size/anchor/depth). Returns false when no iso art
   * is loaded for this asset id, so the caller falls back to the legacy prop path. */
  private drawIsoProp(cmd: RenderFrame['commands'][number], isoManifest: IsoManifest): boolean {
    const resolved = resolveIsoProp(isoManifest, cmd.assetId)
    const textureKey = resolved ? getIsoProp(this, resolved.key) : null
    if (!resolved || !textureKey || !this.layer) return false
    const [ox, oy] = isoPropOrigin(resolved.entry)
    const img = this.add.image(cmd.screenX, cmd.screenY, textureKey).setOrigin(ox, oy)
    img.setDepth(isoDepth(cmd.layer, cmd.screenY) + isoPropDepthOffset(isoManifest, resolved.entry))
    this.layer.add(img)
    return true
  }

  private draw(frame: RenderFrame): void {
    // Remember where each character is displayed right now (mid-glide included) so the
    // redraw can slide from there instead of snapping. Only within the same room.
    const previousPositions = new Map<string, { x: number; y: number }>()
    if (this.lastDrawnRoomId === frame.roomId) {
      this.characterSprites.forEach((sprite, id) => previousPositions.set(id, { x: sprite.x, y: sprite.y }))
    }
    this.tweens.killAll() // tweens target objects destroyed by removeAll() below
    this.characterSprites.clear()
    this.lastDrawnRoomId = frame.roomId
    this.layer?.removeAll(true)
    if (!this.layer) return

    // The backend lays commands out around the viewport centre (e.g. 640,360 for a 1280x720 viewport) while the
    // Phaser canvas is smaller, so centre the camera on it; otherwise the room sits in the bottom-right corner.
    this.cameras.main.centerOn(frame.viewport.width / 2, frame.viewport.height / 2)

    const iso = isIsometric(frame)
    const isoManifest = iso ? getManifest()?.iso ?? null : null
    const ratio = frame.viewport.isoTileRatio ?? 0.5
    // Depth-sorting (end of draw()) is iso-only; the legacy top-down path keeps
    // plain list-order compositing untouched.

    for (const cmd of frame.commands) {
      if (iso && cmd.layer === 'floor') {
        const floorDepth = isoDepth(cmd.layer, cmd.screenY)
        const tileKey = isoManifest ? getIsoTile(this, isoFloorTileKey(frame.roomId)) : null
        if (tileKey) {
          // W-ISO-3: tile the room diamond with the floor art instead of one flat fill.
          const layout = isoFloorTileLayout(cmd.screenX, cmd.screenY, ISO_FLOOR_HALF_WIDTH, ratio)
          for (const t of layout.tiles) {
            const tile = this.add.image(t.x, t.y, tileKey).setDisplaySize(layout.tileWidth, layout.tileHeight)
            tile.setDepth(floorDepth)
            this.layer.add(tile)
          }
        }
        const g = this.add.graphics()
        const pts = isoDiamondPoints(cmd.screenX, cmd.screenY, ISO_FLOOR_HALF_WIDTH, ratio)
        if (!tileKey) g.fillStyle(ISO_FLOOR_FILL, 1) // tiles missing (older manifest): keep the flat floor
        g.lineStyle(2, ISO_FLOOR_EDGE, 1)
        g.beginPath()
        g.moveTo(pts[0][0], pts[0][1])
        for (const [px, py] of pts.slice(1)) g.lineTo(px, py)
        g.closePath()
        if (!tileKey) g.fillPath()
        g.strokePath()
        g.setDepth(floorDepth)
        this.layer.add(g)
      } else if (cmd.layer === 'floor') {
        const buildingKey = DISTRICT_TO_BUILDING[frame.roomId]
        const textureKey = getBuilding(this, buildingKey ?? frame.roomId)
        const bg = this.add.image(cmd.screenX, cmd.screenY, textureKey)
        bg.setDisplaySize(640, 360)
        this.layer.add(bg)
      } else if (cmd.layer === 'furniture' && iso && isoManifest && this.drawIsoProp(cmd, isoManifest)) {
        // drawn by drawIsoProp (isometric art); nothing else to do
      } else if (cmd.layer === 'furniture') {
        const resolved = resolvePropAssetId(cmd.assetId)
        const textureKey = resolved
          ? resolved.kind === 'props'
            ? getProp(this, resolved.name)
            : getDecoration(this, resolved.name)
          : getProp(this, assetDisplayName(cmd.assetId) || 'unknown') // no mapping -> AssetRegistry's own fallback
        const img = this.add.image(cmd.screenX, cmd.screenY, textureKey)
        img.setDisplaySize(FURNITURE_SIZE, FURNITURE_SIZE)
        if (iso) img.setDepth(isoDepth(cmd.layer, cmd.screenY))
        this.layer.add(img)
        const label = this.add.text(cmd.screenX, cmd.screenY + FURNITURE_SIZE / 2 + 2, assetDisplayName(cmd.assetId), {
          fontSize: '9px',
          color: '#94a3b8',
        }).setOrigin(0.5, 0)
        this.layer.add(label)
      } else if (cmd.layer === 'characters') {
        const behavior = (cmd.metadata?.animationState as string) ?? 'idle'
        const role = CHARACTER_TO_ROLE[cmd.entityId] ?? cmd.entityId
        const isoSheet = isoManifest && hasIsoCharacter(isoManifest, cmd.entityId) ? getIsoNPC(this, cmd.entityId) : null
        const textureKey = isoSheet ?? getNPC(this, role)
        const isSpritesheet = textureKey.startsWith('npc_ss__') || isoSheet !== null
        // Isometric sheets are pose strips (frame = pose); legacy sheets are 4 directions.
        // `working` is drawn seated in iso: the character sits at a chair/desk instead of standing.
        const frameIndex = isoSheet && isoManifest
          ? isoPoseFrame(isoManifest.character, isoPoseName(isoManifest.character, behavior, true))
          : getNPCFrame('F')
        const sprite = isSpritesheet
          ? this.add.sprite(cmd.screenX, cmd.screenY, textureKey, frameIndex)
          : this.add.image(cmd.screenX, cmd.screenY, textureKey)
        if (isoSheet && isoManifest) sprite.setOrigin(isoManifest.character.anchor[0], isoManifest.character.anchor[1])
        // Native NPC frames are 140x160 (see world.config.ts); scale to
        // a consistent on-screen height regardless of source size,
        // whether that's a real sprite sheet frame or a fallback square.
        const scale = (isoSheet ? ISO_CHARACTER_DISPLAY_HEIGHT : CHARACTER_DISPLAY_HEIGHT) / sprite.height
        sprite.setScale(scale)
        // Anchored sprites hang from the feet; legacy sprites are centred, so offsets differ.
        const footY = isoSheet ? cmd.screenY : cmd.screenY + sprite.displayHeight / 2
        const topY = isoSheet ? cmd.screenY - sprite.displayHeight * (isoManifest?.character.anchor[1] ?? 1) : cmd.screenY - sprite.displayHeight / 2
        // Behavior still drives an at-a-glance color cue — a thin ring
        // under the sprite, same semantic as the old solid-color circle.
        const ring = this.add.ellipse(
          cmd.screenX, footY - 2,
          sprite.displayWidth * 0.8, 8,
          BEHAVIOR_COLORS[behavior as keyof typeof BEHAVIOR_COLORS] ?? BEHAVIOR_COLORS.idle,
          0.6,
        )
        if (iso) {
          const d = isoDepth(cmd.layer, cmd.screenY)
          ring.setDepth(d - 0.05)
          sprite.setDepth(d)
        }
        this.layer.add(ring)
        this.layer.add(sprite)
        const label = this.add.text(cmd.screenX, topY - 12, cmd.entityId, {
          fontSize: '11px',
          color: '#e2e8f0',
        }).setOrigin(0.5, 1)
        if (iso) label.setDepth(isoDepth(cmd.layer, cmd.screenY) + 0.05)
        this.layer.add(label)
        this.characterSprites.set(cmd.entityId, sprite)
        const offset = characterTweenOffset(
          previousPositions.get(cmd.entityId),
          { x: cmd.screenX, y: cmd.screenY },
          WORLD_CONFIG.characterSnapDistancePx,
        )
        if (offset) {
          const stopWalk =
            isoSheet && isoManifest && sprite instanceof Phaser.GameObjects.Sprite
              ? this.startWalk(sprite, cmd.entityId, isoManifest, offset.dx, offset.dy, isoSheet, frameIndex)
              : null
          this.glide([ring, sprite, label], offset.dx, offset.dy, stopWalk ?? undefined)
        }
      }
    }
    if (iso) this.layer.sort('depth')
  }
}

interface OfficeSceneProps {
  frame: RenderFrame | null
}

export default function OfficeScene({ frame }: OfficeSceneProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const gameRef = useRef<Phaser.Game | null>(null)
  const sceneRef = useRef<OfficeCanvasScene | null>(null)

  useEffect(() => {
    if (!containerRef.current) return
    let cancelled = false
    let game: Phaser.Game | null = null

    // loadManifest() must resolve before the Scene's preload() runs
    // (registerAssets() reads the already-loaded manifest synchronously
    // — see AssetRegistry.ts). If this container unmounts mid-fetch
    // (e.g. fast route navigation), `cancelled` skips creating a game
    // for a container that's no longer in the DOM.
    loadManifest()
      .catch((err) => {
        // A failed fetch (e.g. dev server not serving /assets/world/
        // yet) must not crash the World tab — every AssetRegistry
        // getter already falls back to a coloured placeholder when the
        // manifest never loaded, so proceeding is safe, just less
        // pretty.
        console.warn('OfficeScene: manifest failed to load, using fallback art', err)
      })
      .then(() => {
        if (cancelled || !containerRef.current) return
        const scene = new OfficeCanvasScene()
        sceneRef.current = scene
        game = new Phaser.Game({
          type: Phaser.AUTO,
          width: 720,
          height: 420,
          parent: containerRef.current,
          scene,
          backgroundColor: '#0f172a',
        })
        gameRef.current = game
      })

    return () => {
      cancelled = true
      game?.destroy(true)
      gameRef.current = null
      sceneRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (frame && sceneRef.current) {
      sceneRef.current.setFrame(frame)
    }
  }, [frame])

  return <div ref={containerRef} data-testid="office-scene-canvas" className="rounded-lg overflow-hidden border border-slate-700" />
}
