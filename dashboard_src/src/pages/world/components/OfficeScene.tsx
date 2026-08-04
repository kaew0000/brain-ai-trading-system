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
import { assetDisplayName, BEHAVIOR_COLORS } from '../sceneMapping'
import { CHARACTER_TO_ROLE, DISTRICT_TO_BUILDING, resolvePropAssetId } from '../assetMapping'
import { getBuilding, getDecoration, getNPC, getNPCFrame, getProp, loadManifest, registerAssets } from '../../../game/assets/AssetRegistry'

const FURNITURE_SIZE = 32 // px — matches the footprint the old 28x28 rectangle occupied
const CHARACTER_DISPLAY_HEIGHT = 40 // px — matches the visual weight of the old 14px-radius circle

class OfficeCanvasScene extends Phaser.Scene {
  private frame: RenderFrame | null = null
  private layer?: Phaser.GameObjects.Container

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
    this.frame = frame
    if (this.layer) this.draw(frame)
  }

  private draw(frame: RenderFrame): void {
    this.layer?.removeAll(true)
    if (!this.layer) return

    for (const cmd of frame.commands) {
      if (cmd.layer === 'floor') {
        const buildingKey = DISTRICT_TO_BUILDING[frame.roomId]
        const textureKey = getBuilding(this, buildingKey ?? frame.roomId)
        const bg = this.add.image(cmd.screenX, cmd.screenY, textureKey)
        bg.setDisplaySize(640, 360)
        this.layer.add(bg)
      } else if (cmd.layer === 'furniture') {
        const resolved = resolvePropAssetId(cmd.assetId)
        const textureKey = resolved
          ? resolved.kind === 'props'
            ? getProp(this, resolved.name)
            : getDecoration(this, resolved.name)
          : getProp(this, assetDisplayName(cmd.assetId) || 'unknown') // no mapping -> AssetRegistry's own fallback
        const img = this.add.image(cmd.screenX, cmd.screenY, textureKey)
        img.setDisplaySize(FURNITURE_SIZE, FURNITURE_SIZE)
        this.layer.add(img)
        const label = this.add.text(cmd.screenX, cmd.screenY + FURNITURE_SIZE / 2 + 2, assetDisplayName(cmd.assetId), {
          fontSize: '9px',
          color: '#94a3b8',
        }).setOrigin(0.5, 0)
        this.layer.add(label)
      } else if (cmd.layer === 'characters') {
        const behavior = (cmd.metadata?.animationState as string) ?? 'idle'
        const role = CHARACTER_TO_ROLE[cmd.entityId] ?? cmd.entityId
        const textureKey = getNPC(this, role)
        const isSpritesheet = textureKey.startsWith('npc_ss__')
        const sprite = isSpritesheet
          ? this.add.sprite(cmd.screenX, cmd.screenY, textureKey, getNPCFrame('F'))
          : this.add.image(cmd.screenX, cmd.screenY, textureKey)
        // Native NPC frames are 140x160 (see world.config.ts); scale to
        // a consistent on-screen height regardless of source size,
        // whether that's a real sprite sheet frame or a fallback square.
        const scale = CHARACTER_DISPLAY_HEIGHT / sprite.height
        sprite.setScale(scale)
        // Behavior still drives an at-a-glance color cue — a thin ring
        // under the sprite, same semantic as the old solid-color circle.
        const ring = this.add.ellipse(
          cmd.screenX, cmd.screenY + (sprite.displayHeight / 2) - 2,
          sprite.displayWidth * 0.8, 8,
          BEHAVIOR_COLORS[behavior as keyof typeof BEHAVIOR_COLORS] ?? BEHAVIOR_COLORS.idle,
          0.6,
        )
        this.layer.add(ring)
        this.layer.add(sprite)
        const label = this.add.text(cmd.screenX, cmd.screenY - sprite.displayHeight / 2 - 12, cmd.entityId, {
          fontSize: '11px',
          color: '#e2e8f0',
        }).setOrigin(0.5, 1)
        this.layer.add(label)
      }
    }
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
