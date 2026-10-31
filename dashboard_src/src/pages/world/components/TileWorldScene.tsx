// dashboard_src/src/pages/world/components/TileWorldScene.tsx
// V16 §94 — the walkable Office World. Replaces the isometric OfficeScene (which stays as the fallback when
// manifest.tileWorld is absent/disabled). A top-down tile map (world/scripts/build_tile_world.py) with the
// Universal-LPC characters: the player walks it (WASD / arrows, or click to path-find, walls and furniture
// block), the 16 NPCs go where the simulation says (seat / meeting tile / door / wandering their room), and
// near an NPC `E` (or a click) selects it. All rules live in ../tileWorld.ts; this file only draws and wires.
// Read-only: it consumes /api/world/* data and never calls anything that can place or change a trade.
import Phaser from 'phaser'
import { useEffect, useRef, useState } from 'react'
import { WORLD_CONFIG } from '../../../game/config/world.config'
import { getLpcNPC, getManifest, loadManifest, registerAssets } from '../../../game/assets/AssetRegistry'
import { CHARACTER_TO_ROLE } from '../assetMapping'
import { lpcAnimationName, lpcDirectionFromDelta, lpcFrameIndex, lpcFrameRange, type LpcDirection, type LpcManifest } from '../lpcAssets'
import {
  avatarChoices,
  findPath,
  footPoint,
  inputVector,
  isTypingTarget,
  moveWithCollision,
  nearestCharacter,
  npcGoal,
  parseTileMap,
  resolveAvatar,
  restingAnimation,
  roomAtTile,
  roomById,
  stepAlong,
  tileOfFeet,
  worldToTile,
  type Point,
  type Tile,
  type TileMap,
} from '../tileWorld'
import type { CharacterActivity, RoomActivity } from '../types'

const ATLAS_KEY = 'tile_world_atlas'
const MAP_KEY = 'tile_world_map'
const TW = WORLD_CONFIG.tileWorld
const LABEL_DEPTH = 1_000_000
const ACTIVITY_TINT: Record<string, { color: number; alpha: number }> = {
  meeting: { color: 0x38bdf8, alpha: 0.14 },
  alert: { color: 0xf59e0b, alpha: 0.2 },
  critical: { color: 0xef4444, alpha: 0.28 },
  celebration: { color: 0x22c55e, alpha: 0.18 },
}

interface Walker {
  id: string
  role: string
  sprite: Phaser.GameObjects.Sprite
  label: Phaser.GameObjects.Text
  pos: Point
  path: Point[]
  facing: LpcDirection
  /** Key of the visual state currently applied, so animations are only restarted on a real change. */
  visual: string
  goalKey: string
  behavior: string
  atSeat: boolean
  seatFacing: LpcDirection | null
}

export interface TileWorldHandlers {
  onRoomChange?: (roomId: string, roomName: string) => void
  onNearby?: (agentId: string | null) => void
  onSelectCharacter?: (agentId: string) => void
  onError?: (message: string) => void
  onReady?: () => void
}

class TileWorldCanvasScene extends Phaser.Scene {
  handlers: TileWorldHandlers = {}
  private map!: TileMap
  private lpc!: LpcManifest
  private ready = false
  private player: Walker | null = null
  private npcs = new Map<string, Walker>()
  private overlays = new Map<string, Phaser.GameObjects.Rectangle>()
  private keys: Record<string, Phaser.Input.Keyboard.Key> | null = null
  private capturing = false
  private nearby: string | null = null
  private currentRoomId: string | null = null
  private pendingChars: CharacterActivity[] = []
  private pendingTick = 0
  private pendingRooms: RoomActivity[] = []
  private pendingAvatar: string | null = null
  private pendingWalk: string | null = null

  constructor() {
    super('tile-world')
  }

  preload(): void {
    registerAssets(this) // LPC sheets (and the legacy art the other tabs share)
    const tw = getManifest()?.tileWorld
    if (!tw) return
    this.load.atlas(ATLAS_KEY, tw.atlas.image, tw.atlas.data)
    this.load.json(MAP_KEY, tw.map)
  }

  create(): void {
    try {
      const lpc = getManifest()?.lpc
      if (!lpc?.enabled) throw new Error('LPC character sheets are not enabled in the manifest')
      this.lpc = lpc
      this.map = parseTileMap(this.cache.json.get(MAP_KEY))
    } catch (err) {
      this.handlers.onError?.(err instanceof Error ? err.message : String(err))
      return
    }
    this.textures.get(ATLAS_KEY).setFilter(Phaser.Textures.FilterMode.NEAREST)
    const { tileSize: ts } = this.map

    this.map.floor.forEach((row, y) =>
      row.forEach((idx, x) => this.add.image(x * ts, y * ts, ATLAS_KEY, this.map.tiles[idx]).setOrigin(0, 0).setDepth(0)),
    )
    for (const room of this.map.rooms) {
      const [rx, ry, rw, rh] = room.rect
      this.overlays.set(room.id, this.add.rectangle(rx * ts, ry * ts, rw * ts, rh * ts, 0xffffff, 0).setOrigin(0, 0).setDepth(0.5))
      this.add
        .text((rx + rw / 2) * ts, ry * ts - 6, room.name, { fontSize: '10px', color: '#e2e8f0', backgroundColor: '#0f172acc', padding: { x: 3, y: 1 } })
        .setOrigin(0.5, 1)
        .setDepth(LABEL_DEPTH - 1)
    }
    for (const p of this.map.props) this.add.image(p.x, p.y, ATLAS_KEY, p.frame).setOrigin(0.5, 1).setDepth(p.depth)

    const cam = this.cameras.main
    cam.setBounds(0, 0, this.map.width, this.map.height)
    cam.setZoom(TW.cameraZoom)
    cam.roundPixels = true

    const kb = this.input.keyboard
    if (kb) {
      // enableCapture=false: a captured W/A/S/D/E would be swallowed by the chat box (preventDefault).
      this.keys = kb.addKeys(
        { up: 'W', down: 'S', left: 'A', right: 'D', up2: 'UP', down2: 'DOWN', left2: 'LEFT', right2: 'RIGHT', talk: 'E' },
        false,
      ) as Record<string, Phaser.Input.Keyboard.Key>
    }
    this.input.on('pointerdown', this.onPointer, this)
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => this.cleanup())

    const role = this.pendingAvatar ?? getManifest()?.tileWorld?.defaultAvatar ?? Object.keys(this.lpc.sheets)[0]
    this.player = this.makeWalker('__player__', role, 'You', footPoint(this.map, this.map.spawn.tile), this.map.spawn.facing)
    if (!this.player) {
      this.handlers.onError?.(`no LPC sheet for avatar role ${role}`)
      return
    }
    cam.startFollow(this.player.sprite, true, TW.cameraLerp, TW.cameraLerp)

    this.ready = true
    this.applyRooms()
    this.applySimulation()
    if (this.pendingWalk) this.walkToRoom(this.pendingWalk)
    this.handlers.onReady?.()
  }

  // ── public API (called from React) ─────────────────────────────────────────

  setSimulation(characters: CharacterActivity[], tick: number): void {
    this.pendingChars = characters
    this.pendingTick = tick
    if (this.ready) this.applySimulation()
  }

  setRooms(rooms: RoomActivity[]): void {
    this.pendingRooms = rooms
    if (this.ready) this.applyRooms()
  }

  setAvatar(role: string): void {
    this.pendingAvatar = role
    // Not booted yet (React calls this before Phaser starts the scene): create() applies pendingAvatar.
    // Touching this.textures here would crash on every mount after the first, once the registry has keys.
    if (!this.ready || !this.player) return
    const p = this.player
    const sheet = getLpcNPC(this, role)
    if (!sheet) return
    p.role = role
    p.sprite.setTexture(sheet)
    p.visual = ''
  }

  walkToRoom(roomId: string): void {
    if (!this.ready || !this.player) {
      this.pendingWalk = roomId
      return
    }
    this.pendingWalk = null
    const room = roomById(this.map, roomId)
    if (room) this.routeTo(this.player, room.meet)
  }

  // ── internals ──────────────────────────────────────────────────────────────

  private makeWalker(id: string, role: string, name: string, pos: Point, facing: LpcDirection): Walker | null {
    const sheet = getLpcNPC(this, role)
    if (!sheet) {
      console.warn(`tile world: no LPC sheet for role ${role}`)
      return null
    }
    this.textures.get(sheet).setFilter(Phaser.Textures.FilterMode.NEAREST)
    const sprite = this.add.sprite(pos.x, pos.y, sheet, 0).setOrigin(this.lpc.anchor[0], this.lpc.anchor[1])
    sprite.setScale(this.lpc.displayHeight / sprite.height)
    const label = this.add
      .text(pos.x, pos.y, name, { fontSize: '10px', color: id === '__player__' ? '#fde68a' : '#e2e8f0', backgroundColor: '#0f172acc', padding: { x: 3, y: 1 } })
      .setOrigin(0.5, 1)
      .setDepth(LABEL_DEPTH)
    const w: Walker = { id, role, sprite, label, pos: { ...pos }, path: [], facing, visual: '', goalKey: '', behavior: 'idle', atSeat: false, seatFacing: null }
    this.render(w, false, 'idle')
    return w
  }

  private render(w: Walker, moving: boolean, behavior: string): void {
    const sheet = getLpcNPC(this, w.role)
    if (!sheet) return
    const anim = moving ? lpcAnimationName(this.lpc, w.role, 'walking') : restingAnimation(this.lpc, w.role, behavior)
    const looping = this.lpc.animations[anim]?.frames > 1
    const visual = `${w.role}|${anim}|${w.facing}|${looping ? 'loop' : 'still'}`
    if (visual !== w.visual) {
      w.visual = visual
      if (looping) {
        const key = `tw_${w.role}_${anim}_${w.facing}`
        if (!this.anims.exists(key)) {
          const { start, end } = lpcFrameRange(this.lpc, anim, w.facing)
          this.anims.create({ key, frames: this.anims.generateFrameNumbers(sheet, { start, end }), frameRate: this.lpc.animations[anim].fps, repeat: -1 })
        }
        w.sprite.play(key, true)
      } else {
        w.sprite.anims.stop()
        w.sprite.setFrame(lpcFrameIndex(this.lpc, anim, w.facing, 0))
      }
    }
    w.sprite.setPosition(w.pos.x, w.pos.y).setDepth(w.pos.y)
    w.label.setPosition(w.pos.x, w.pos.y - this.lpc.displayHeight * this.lpc.anchor[1] - 2)
  }

  private routeTo(w: Walker, tile: Tile): void {
    const path = findPath(this.map, tileOfFeet(this.map, w.pos), tile)
    w.path = path ? path.map((t) => footPoint(this.map, t)) : []
  }

  private applyRooms(): void {
    const active = new Map(this.pendingRooms.map((r) => [r.roomId, r.activity]))
    this.overlays.forEach((rect, id) => {
      const tint = ACTIVITY_TINT[active.get(id) ?? '']
      if (tint) rect.setFillStyle(tint.color, tint.alpha)
      else rect.setFillStyle(0xffffff, 0)
    })
  }

  private applySimulation(): void {
    const seen = new Set<string>()
    for (const c of this.pendingChars) {
      const room = roomById(this.map, c.roomId)
      if (!room) continue
      seen.add(c.agentId)
      const goal = npcGoal(room, c.agentId, c.behavior, this.pendingTick)
      let npc = this.npcs.get(c.agentId)
      if (!npc) {
        const role = CHARACTER_TO_ROLE[c.agentId] ?? 'office_worker'
        const made = this.makeWalker(c.agentId, role, c.agentId, footPoint(this.map, goal.tile), goal.facing ?? 'down')
        if (!made) continue
        npc = made
        this.npcs.set(c.agentId, npc)
        npc.sprite.setInteractive({ useHandCursor: true })
        npc.goalKey = `${room.id}|${goal.tile.join(',')}`
      } else {
        const key = `${room.id}|${goal.tile.join(',')}`
        if (key !== npc.goalKey) {
          npc.goalKey = key
          this.routeTo(npc, goal.tile)
        }
      }
      npc.behavior = c.behavior
      npc.atSeat = goal.atSeat
      npc.seatFacing = goal.facing
    }
    this.npcs.forEach((npc, id) => {
      if (seen.has(id)) return
      npc.sprite.destroy()
      npc.label.destroy()
      this.npcs.delete(id)
    })
  }

  private onPointer(pointer: Phaser.Input.Pointer): void {
    if (!this.player) return
    const wx = pointer.worldX
    const wy = pointer.worldY
    for (const npc of this.npcs.values()) {
      if (Math.hypot(npc.pos.x - wx, npc.pos.y - this.lpc.displayHeight / 2 - wy) <= 28) {
        this.routeTo(this.player, worldToTile(this.map, npc.pos.x, npc.pos.y))
        this.handlers.onSelectCharacter?.(npc.id)
        return
      }
    }
    this.routeTo(this.player, worldToTile(this.map, wx, wy))
  }

  update(_time: number, delta: number): void {
    if (!this.ready || !this.player) return
    const dt = Math.min(delta, 100) / 1000
    const typing = isTypingTarget(document.activeElement as HTMLElement | null)
    this.syncCapture(!typing)

    // player: keyboard wins over a click-to-move path
    const k = this.keys
    const v = !typing && k
      ? inputVector({
          up: k.up.isDown || k.up2.isDown,
          down: k.down.isDown || k.down2.isDown,
          left: k.left.isDown || k.left2.isDown,
          right: k.right.isDown || k.right2.isDown,
        })
      : { x: 0, y: 0 }
    const p = this.player
    let moved = { dx: 0, dy: 0 }
    if (v.x !== 0 || v.y !== 0) {
      p.path = []
      const next = moveWithCollision(this.map, p.pos, v.x * TW.playerSpeedPxPerSec * dt, v.y * TW.playerSpeedPxPerSec * dt)
      moved = { dx: next.x - p.pos.x, dy: next.y - p.pos.y }
      p.pos = next
    } else if (p.path.length) {
      const step = stepAlong(p.pos, p.path, TW.playerSpeedPxPerSec, dt)
      p.pos = step.pos
      p.path = step.rest
      moved = { dx: step.dx, dy: step.dy }
    }
    const playerMoving = moved.dx !== 0 || moved.dy !== 0
    if (playerMoving) p.facing = lpcDirectionFromDelta(moved.dx, moved.dy, p.facing)
    this.render(p, playerMoving, 'idle')

    this.npcs.forEach((npc) => {
      const step = stepAlong(npc.pos, npc.path, TW.npcSpeedPxPerSec, dt)
      npc.pos = step.pos
      npc.path = step.rest
      const moving = step.dx !== 0 || step.dy !== 0
      if (moving) npc.facing = lpcDirectionFromDelta(step.dx, step.dy, npc.facing)
      else if (npc.atSeat && npc.seatFacing) npc.facing = npc.seatFacing
      this.render(npc, moving, npc.behavior)
    })

    const near = nearestCharacter([...this.npcs.values()].map((n) => ({ id: n.id, x: n.pos.x, y: n.pos.y })), p.pos, TW.interactRangePx)
    if (near !== this.nearby) {
      this.nearby = near
      this.handlers.onNearby?.(near)
    }
    if (k && !typing && Phaser.Input.Keyboard.JustDown(k.talk) && this.nearby) this.handlers.onSelectCharacter?.(this.nearby)

    const room = roomAtTile(this.map, tileOfFeet(this.map, p.pos))
    if (room && room.id !== this.currentRoomId) {
      this.currentRoomId = room.id
      this.handlers.onRoomChange?.(room.id, room.name)
    }
  }

  /** Stop swallowing arrow keys (page scroll) while the user types in a field. */
  private syncCapture(wanted: boolean): void {
    const kb = this.input.keyboard
    if (!kb || wanted === this.capturing) return
    this.capturing = wanted
    if (wanted) kb.addCapture('UP,DOWN,LEFT,RIGHT')
    else kb.removeCapture('UP,DOWN,LEFT,RIGHT')
  }

  private cleanup(): void {
    this.input.off('pointerdown', this.onPointer, this)
    this.input.keyboard?.removeCapture('UP,DOWN,LEFT,RIGHT')
    this.npcs.clear()
    this.overlays.clear()
    this.player = null
    this.ready = false
  }
}

interface TileWorldSceneProps {
  characters: CharacterActivity[]
  rooms: RoomActivity[]
  tick: number
  /** Ask the player to walk to a room; a new nonce re-triggers the same room. */
  walkTo?: { roomId: string; nonce: number } | null
  onSelectCharacter?: (agentId: string) => void
  onRoomChange?: (roomId: string) => void
  /** Called when the tile world cannot start (manifest disabled / assets missing) so the page can fall back. */
  onUnavailable?: (reason: string) => void
}

function loadStoredAvatar(): string | null {
  try {
    return window.localStorage.getItem(TW.avatarStorageKey)
  } catch {
    return null // storage blocked (private mode): the choice just is not remembered
  }
}

function storeAvatar(role: string): void {
  try {
    window.localStorage.setItem(TW.avatarStorageKey, role)
  } catch {
    /* not remembered */
  }
}

export default function TileWorldScene({ characters, rooms, tick, walkTo, onSelectCharacter, onRoomChange, onUnavailable }: TileWorldSceneProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<TileWorldCanvasScene | null>(null)
  const callbacks = useRef({ onSelectCharacter, onRoomChange, onUnavailable })
  callbacks.current = { onSelectCharacter, onRoomChange, onUnavailable }
  // The scene is created asynchronously (manifest fetch); it must be handed whatever data already arrived,
  // not just later changes, so keep the latest props where the creation callback can read them.
  const latest = useRef({ characters, rooms, tick, walkTo })
  latest.current = { characters, rooms, tick, walkTo }
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [errorText, setErrorText] = useState('')
  const [roomName, setRoomName] = useState('')
  const [nearby, setNearby] = useState<string | null>(null)
  const [choices, setChoices] = useState<string[]>([])
  const [avatar, setAvatar] = useState('')

  useEffect(() => {
    if (!containerRef.current) return
    let cancelled = false
    let game: Phaser.Game | null = null
    loadManifest()
      .catch((err) => console.warn('tile world: manifest failed to load', err))
      .then(() => {
        const manifest = getManifest()
        if (cancelled || !containerRef.current) return
        if (!manifest?.tileWorld?.enabled || !manifest.lpc?.enabled) {
          setStatus('error')
          setErrorText('Tile world is not enabled in the asset manifest')
          callbacks.current.onUnavailable?.('disabled')
          return
        }
        const list = avatarChoices(Object.keys(manifest.lpc.sheets), manifest.tileWorld.defaultAvatar)
        const chosen = resolveAvatar(loadStoredAvatar(), list)
        setChoices(list)
        setAvatar(chosen)
        const scene = new TileWorldCanvasScene()
        scene.setAvatar(chosen)
        scene.handlers = {
          onReady: () => setStatus('ready'),
          onError: (msg) => {
            setStatus('error')
            setErrorText(msg)
            callbacks.current.onUnavailable?.(msg)
          },
          onNearby: setNearby,
          onRoomChange: (id, name) => {
            setRoomName(name)
            callbacks.current.onRoomChange?.(id)
          },
          onSelectCharacter: (id) => callbacks.current.onSelectCharacter?.(id),
        }
        sceneRef.current = scene
        scene.setSimulation(latest.current.characters, latest.current.tick)
        scene.setRooms(latest.current.rooms)
        if (latest.current.walkTo) scene.walkToRoom(latest.current.walkTo.roomId)
        game = new Phaser.Game({
          type: Phaser.AUTO,
          parent: containerRef.current,
          scene,
          backgroundColor: '#0f172a',
          pixelArt: true,
          scale: { mode: Phaser.Scale.RESIZE, width: '100%', height: '100%' },
        })
      })
    return () => {
      cancelled = true
      game?.destroy(true)
      sceneRef.current = null
    }
  }, [])

  useEffect(() => { sceneRef.current?.setSimulation(characters, tick) }, [characters, tick])
  useEffect(() => { sceneRef.current?.setRooms(rooms) }, [rooms])
  useEffect(() => { if (walkTo) sceneRef.current?.walkToRoom(walkTo.roomId) }, [walkTo])

  const changeAvatar = (role: string) => {
    setAvatar(role)
    storeAvatar(role)
    sceneRef.current?.setAvatar(role)
  }

  return (
    <div className="space-y-2" data-testid="tile-world">
      <div
        ref={containerRef}
        data-testid="tile-world-canvas"
        style={{ height: TW.canvasHeightPx, maxHeight: '70vh' }}
        className="w-full rounded-lg overflow-hidden border border-slate-700 bg-slate-900"
      />
      {status === 'error' && <p className="text-xs text-rose-400" role="alert" data-testid="tile-world-error">{errorText}</p>}
      <div className="flex flex-wrap items-center gap-3 text-xs text-slate-400" data-testid="tile-world-hud">
        <span>WASD / arrows to walk · click to go there · E to talk</span>
        {roomName && <span className="rounded-full bg-slate-800 px-2 py-1 text-slate-200" data-testid="tile-world-room">{roomName}</span>}
        {nearby && (
          <button
            type="button"
            data-testid="tile-world-nearby"
            onClick={() => callbacks.current.onSelectCharacter?.(nearby)}
            className="rounded-full border border-emerald-600 px-2 py-1 text-emerald-300 hover:bg-emerald-950"
          >
            Talk to {nearby} (E)
          </button>
        )}
        {choices.length > 0 && (
          <label className="ml-auto flex items-center gap-1">
            Avatar
            <select
              data-testid="tile-world-avatar"
              value={avatar}
              onChange={(e) => changeAvatar(e.target.value)}
              className="rounded border border-slate-700 bg-slate-900 px-1 py-0.5 text-slate-200"
            >
              {choices.map((c) => <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>)}
            </select>
          </label>
        )}
      </div>
    </div>
  )
}
