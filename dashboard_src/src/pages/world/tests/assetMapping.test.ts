// dashboard_src/src/pages/world/tests/assetMapping.test.ts
// Tests the translation tables bridging backend asset ids
// (world/data/assets/asset_manifest.json) to the frontend's real
// manifest keys (dashboard_src/public/assets/world/manifest.json).
import { describe, expect, it } from 'vitest'
import {
  CHARACTER_TO_ROLE,
  DECORATION_ASSET_TO_KEY,
  DISTRICT_TO_BUILDING,
  FURNITURE_ASSET_TO_PROP,
  resolvePropAssetId,
} from '../assetMapping'

// The real district ids, from world/districts/definitions/*.json,
// duplicated here (not imported — this is a frontend-only test file
// with no Python interop) so a rename in either place shows up as a
// failing test rather than a silent gap.
const REAL_DISTRICT_IDS = [
  'ai-council', 'ceo-tower', 'command-hall', 'data-center', 'execution-forge',
  'journal-library', 'market-intelligence-center', 'portfolio-garden',
  'recovery-center', 'research-district', 'risk-fortress', 'simulation-lab',
  'training-arena', 'world-gateway',
]

const REAL_CHARACTER_IDS = [
  'bastion', 'chameleon', 'chronos', 'crucible', 'echo', 'forge', 'gardener',
  'herald', 'mandelbrot', 'oracle', 'phoenix', 'primus', 'scribe', 'sentinel',
  'watcher', 'webweaver',
]

// The frontend's real manifest keys (dashboard_src/public/assets/
// world/manifest.json), duplicated here for the same reason as above.
const REAL_NPC_ROLES = [
  'ceo', 'data_analyst', 'ml_scientist', 'office_worker', 'player',
  'quant_researcher', 'risk_manager', 'security_officer', 'trader',
  'visitor_1', 'visitor_2',
]
const REAL_BUILDING_KEYS = [
  'buildings_sheet', 'ceo_room', 'command_center', 'data_center',
  'futures_trading_lab', 'intelligence_lab', 'mission_board_center',
  'ml_lab', 'portfolio_vault', 'replay_theater', 'research_facility',
  'risk_center', 'server_room', 'teleport_entrance',
]
const REAL_PROP_KEYS = [
  'ai_core', 'conference_setup', 'data_panel_a', 'data_panel_b', 'desk_double',
  'desk_single', 'desk_triple', 'display_lg', 'display_sm', 'gadget_a',
  'gadget_b', 'gadget_c', 'headset', 'keyboard', 'meeting_table', 'phone',
  'props_sheet', 'robot_arm', 'server_rack_lg', 'server_rack_sm', 'tablet',
  'trading_screen', 'vault_door',
]
const REAL_DECORATION_KEYS = [
  'bench', 'billboard_btc', 'billboard_nft', 'bush_a', 'bush_b', 'bush_c',
  'electric_pole', 'flower_a', 'flower_b', 'flower_c', 'fountain_a',
  'fountain_b', 'garden_edge_a', 'garden_edge_b', 'hologram_a', 'hologram_b',
  'hologram_c', 'hydrant', 'lamp_pink', 'led_sign_a', 'led_sign_b',
  'security_camera', 'server_tower_a', 'server_tower_b', 'statue_brain',
  'statue_bull', 'statue_creator', 'street_lamp_a', 'street_lamp_b',
  'street_lamp_c', 'trash_bin', 'tree_oak', 'tree_palm_a', 'tree_palm_b',
  'utility_box',
]

describe('DISTRICT_TO_BUILDING', () => {
  it('has an entry for every real district', () => {
    for (const id of REAL_DISTRICT_IDS) {
      expect(DISTRICT_TO_BUILDING[id]).toBeDefined()
    }
  })

  it('never maps to a building key that does not exist in the real manifest', () => {
    for (const key of Object.values(DISTRICT_TO_BUILDING)) {
      expect(REAL_BUILDING_KEYS).toContain(key)
    }
  })

  it('has no unrecognized district ids (catches typos immediately)', () => {
    for (const id of Object.keys(DISTRICT_TO_BUILDING)) {
      expect(REAL_DISTRICT_IDS).toContain(id)
    }
  })
})

describe('CHARACTER_TO_ROLE', () => {
  it('has an entry for every real character codename', () => {
    for (const id of REAL_CHARACTER_IDS) {
      expect(CHARACTER_TO_ROLE[id]).toBeDefined()
    }
  })

  it('never maps to a role that does not exist in the real manifest', () => {
    for (const role of Object.values(CHARACTER_TO_ROLE)) {
      expect(REAL_NPC_ROLES).toContain(role)
    }
  })

  it('has no unrecognized character ids', () => {
    for (const id of Object.keys(CHARACTER_TO_ROLE)) {
      expect(REAL_CHARACTER_IDS).toContain(id)
    }
  })

  it('does NOT use the old, wrong "_agent"-suffixed vocabulary', () => {
    // Regression guard for the actual root cause this fix addresses:
    // AssetRegistry.ts's old AGENT_TO_ROLE was keyed by ids like
    // "ceo_agent" that never appeared anywhere in real RenderCommand
    // data (which uses codenames like "primus").
    for (const id of Object.keys(CHARACTER_TO_ROLE)) {
      expect(id.endsWith('_agent')).toBe(false)
    }
  })
})

describe('FURNITURE_ASSET_TO_PROP / DECORATION_ASSET_TO_KEY', () => {
  it('never maps furniture to a prop key that does not exist in the real manifest', () => {
    for (const key of Object.values(FURNITURE_ASSET_TO_PROP)) {
      expect(REAL_PROP_KEYS).toContain(key)
    }
  })

  it('never maps decoration to a key that does not exist in the real manifest', () => {
    for (const key of Object.values(DECORATION_ASSET_TO_KEY)) {
      expect(REAL_DECORATION_KEYS).toContain(key)
    }
  })
})

describe('resolvePropAssetId', () => {
  it('resolves a mapped furniture id to its props key', () => {
    expect(resolvePropAssetId('furniture.desk')).toEqual({ kind: 'props', name: 'desk_single' })
  })

  it('resolves a mapped decoration id to its decorations key', () => {
    expect(resolvePropAssetId('decoration.reception-signage')).toEqual({ kind: 'decorations', name: 'led_sign_a' })
  })

  it('returns null for an unmapped furniture id (e.g. door) rather than guessing', () => {
    expect(resolvePropAssetId('furniture.door')).toBeNull()
  })

  it('returns null for null/undefined (the floor-command case)', () => {
    expect(resolvePropAssetId(null)).toBeNull()
    expect(resolvePropAssetId(undefined)).toBeNull()
  })

  it('returns null for an assetId with no category prefix', () => {
    expect(resolvePropAssetId('desk')).toBeNull()
  })

  it('returns null for an unrecognized category', () => {
    expect(resolvePropAssetId('sprite.bastion.idle')).toBeNull()
  })
})
