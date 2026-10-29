// Regression: OfficeScene builds a new Phaser.Game on every World-page mount. The registry must queue
// texture loads for each new game (decided by that game's own texture manager), not only the first one.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import worldManifest from '../../../../public/assets/world/manifest.json'
import { getBuilding, getIsoProp, loadManifest, registerAssets } from '../../../game/assets/AssetRegistry'

function fakeScene() {
  const textures = new Set<string>()
  const queued: string[] = []
  const scene = {
    textures: { exists: (key: string) => textures.has(key) },
    load: {
      image: (key: string) => queued.push(key),
      spritesheet: (key: string) => queued.push(key),
    },
  }
  // simulate the loader finishing: queued keys become real textures
  const finishLoading = () => queued.forEach((k) => textures.add(k))
  return { scene: scene as never, queued, finishLoading }
}

describe('AssetRegistry across Phaser game remounts', () => {
  beforeEach(async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => worldManifest })))
    await loadManifest()
  })

  it('queues the same loads for a second game that has no textures yet', () => {
    const first = fakeScene()
    registerAssets(first.scene)
    first.finishLoading()
    expect(first.queued.length).toBeGreaterThan(0)

    const second = fakeScene() // new Phaser.Game after navigating away and back
    registerAssets(second.scene)
    expect(second.queued.sort()).toEqual(first.queued.sort())
  })

  it('does not re-queue textures a game already has', () => {
    const one = fakeScene()
    registerAssets(one.scene)
    one.finishLoading()
    const again = fakeScene()
    again.finishLoading()
    registerAssets(one.scene) // same game, textures already loaded
    expect(one.queued.length).toBeGreaterThan(0)
    const before = one.queued.length
    registerAssets(one.scene)
    expect(one.queued.length).toBe(before)
  })

  it('exposes iso props only once the scene really has the texture', () => {
    const g = fakeScene()
    registerAssets(g.scene)
    expect(getIsoProp(g.scene, 'desk')).toBeNull()
    g.finishLoading()
    expect(getIsoProp(g.scene, 'desk')).not.toBeNull()
  })

  // V16 §92: lobby/hallway/elevator are not districts, so OfficeScene looks them up by room id.
  it.each(['lobby', 'hallway', 'elevator', 'recovery_center', 'journal_library', 'training_arena'])(
    'resolves the %s backdrop to real art (not the placeholder) once loaded',
    (name) => {
      const g = fakeScene()
      registerAssets(g.scene)
      g.finishLoading()
      expect(getBuilding(g.scene, name)).not.toMatch(/^fallback_/)
    },
  )
})
