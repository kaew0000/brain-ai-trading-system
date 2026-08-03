// dashboard_src/src/pages/world/components/OfficeScene.tsx
// Phase W10 — the actual Phaser 3 rendering surface, consuming Phase W8's
// RenderFrame wire format directly. No PNG sprite/tile assets exist yet
// (Phase W6 only built asset *metadata* — see world/docs/ASSET_PIPELINE.md
// §"Why loaders return metadata, not pixels") so this draws real,
// data-driven Phaser Graphics primitives (rectangles for furniture/floor,
// circles + labels for characters, colored by Phase W7 behavior) rather
// than inventing placeholder sprite images. Every position, color, and
// label comes from the real RenderFrame — nothing here is mocked.

import Phaser from 'phaser'
import { useEffect, useRef } from 'react'
import type { RenderFrame } from '../types'
import { assetDisplayName, BEHAVIOR_COLORS } from '../sceneMapping'

const FLOOR_COLOR = 0x1e293b
const FURNITURE_COLOR = 0x475569
const CHARACTER_RADIUS = 14

class OfficeCanvasScene extends Phaser.Scene {
  private frame: RenderFrame | null = null
  private layer?: Phaser.GameObjects.Container

  constructor() {
    super('OfficeCanvasScene')
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
        const rect = this.add.rectangle(cmd.screenX, cmd.screenY, 640, 360, FLOOR_COLOR)
        rect.setStrokeStyle(2, 0x334155)
        this.layer.add(rect)
      } else if (cmd.layer === 'furniture') {
        const rect = this.add.rectangle(cmd.screenX, cmd.screenY, 28, 28, FURNITURE_COLOR)
        this.layer.add(rect)
        const label = this.add.text(cmd.screenX, cmd.screenY + 18, assetDisplayName(cmd.assetId), {
          fontSize: '9px',
          color: '#94a3b8',
        }).setOrigin(0.5, 0)
        this.layer.add(label)
      } else if (cmd.layer === 'characters') {
        const behavior = (cmd.metadata?.animationState as string) ?? 'idle'
        const color = BEHAVIOR_COLORS[behavior as keyof typeof BEHAVIOR_COLORS] ?? BEHAVIOR_COLORS.idle
        const circle = this.add.circle(cmd.screenX, cmd.screenY, CHARACTER_RADIUS, color)
        circle.setStrokeStyle(2, 0xffffff, 0.6)
        this.layer.add(circle)
        const label = this.add.text(cmd.screenX, cmd.screenY - CHARACTER_RADIUS - 12, cmd.entityId, {
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
    const scene = new OfficeCanvasScene()
    sceneRef.current = scene
    const game = new Phaser.Game({
      type: Phaser.AUTO,
      width: 720,
      height: 420,
      parent: containerRef.current,
      scene,
      backgroundColor: '#0f172a',
    })
    gameRef.current = game
    return () => {
      game.destroy(true)
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
