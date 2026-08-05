// dashboard_src/src/pages/world/assetMapping.ts
//
// Bridges two asset-id vocabularies that grew independently and never
// got connected:
//
//   - Backend (world/data/assets/asset_manifest.json, Phase W6):
//     RenderCommand.assetId values like "furniture.desk",
//     "decoration.wall-clock". Every entry in that manifest has an
//     empty `variants` array — the ids are real and stable, but no
//     real file was ever bound to any of them.
//   - Frontend (dashboard_src/public/assets/world/manifest.json +
//     AssetRegistry.ts): real PNG files exist, keyed by a completely
//     different, simpler vocabulary ("desk_single", "wall-clock" isn't
//     even present).
//
// Floor is a third case: RenderCommand.layer === 'floor' always has
// assetId=null (see world/frontend/renderer/room_renderer.py) — floor
// was never meant to resolve through the asset manifest at all. What
// IS available per frame is RenderFrame.roomId, so floor uses the
// frontend's `buildings` category (14 keys) as a per-room background
// image, matched by what each district id/theme actually is — not the
// frontend's separate `tiles` category, which is a generic top-down
// tileset (grass/road/water/portal) with no thematic connection to an
// office building.
//
// Every table below was built by reading both vocabularies in full
// (not guessed) — see the W11-follow-up report for the complete
// backend/frontend key inventories. Where no reasonable match exists,
// the entry is simply omitted; AssetRegistry's own getters already
// fall back to a coloured placeholder for any unmapped name, so an
// omission here degrades gracefully rather than rendering wrong art.

/** world/districts/definitions/*.json's `id` -> frontend `buildings` key.
 * Grounded in each district's real name/visualTheme; the four weakest
 * fits (no district content thematically matches an available building
 * image) are flagged inline rather than left looking equally confident
 * as the exact matches. */
export const DISTRICT_TO_BUILDING: Record<string, string> = {
  'ceo-tower': 'ceo_room', // exact
  'command-hall': 'command_center', // exact
  'data-center': 'data_center', // exact (id match)
  'execution-forge': 'futures_trading_lab', // trading floor -> trading lab
  'market-intelligence-center': 'intelligence_lab', // exact
  'portfolio-garden': 'portfolio_vault', // portfolio -> vault
  'risk-fortress': 'risk_center', // exact
  'research-district': 'research_facility', // exact
  'ai-council': 'ml_lab', // AI department -> ML lab
  'simulation-lab': 'replay_theater', // "projection room, holographic displays" -> theater
  'world-gateway': 'teleport_entrance', // reception/entrance -> exact semantic match
  'training-arena': 'mission_board_center', // weak: no training-specific building art exists
  'journal-library': 'server_room', // weak: "records/archive" has no direct building match
  'recovery-center': 'buildings_sheet', // weakest: no semantic match found at all
}

/** Character codename (world/characters/definitions/*.json's id, e.g.
 * "primus") -> frontend NPC role (dashboard_src/public/assets/world/
 * manifest.json's `npc` keys). 16 characters share 11 generic office
 * roles, so reuse is unavoidable — matched by each character's real
 * district/department where the role vocabulary allows a sensible fit,
 * generic office_worker used where nothing closer exists. This is a
 * cosmetic/display choice, not derived from any system of record. */
export const CHARACTER_TO_ROLE: Record<string, string> = {
  primus: 'ceo', // CEO Office
  chameleon: 'ml_scientist', // AI Department
  echo: 'office_worker', // Command Center
  chronos: 'security_officer', // Command Center (2nd occupant)
  webweaver: 'data_analyst', // Server Room
  forge: 'trader', // Trading Floor
  scribe: 'office_worker', // Journal Department (record-keeping)
  watcher: 'quant_researcher', // Market Intelligence Center
  gardener: 'office_worker', // Garden — no closer role available
  phoenix: 'visitor_1', // Recovery Center — no closer role available
  oracle: 'quant_researcher', // Research Lab
  mandelbrot: 'ml_scientist', // Research Lab / Simulation Room
  bastion: 'risk_manager', // Risk Department
  sentinel: 'security_officer', // Risk Department (2nd occupant)
  crucible: 'quant_researcher', // Training Room
  herald: 'visitor_2', // Reception
}

/** Backend `furniture.<name>` (stripped of the "furniture." prefix) ->
 * frontend `props` key. Doors/windows/cabinets have no equivalent prop
 * art at all and are deliberately left unmapped. */
export const FURNITURE_ASSET_TO_PROP: Record<string, string> = {
  desk: 'desk_single', // exact
  'meeting-table': 'meeting_table', // exact
  'server-rack': 'server_rack_lg', // exact
  monitor: 'display_sm',
  whiteboard: 'display_lg',
  laptop: 'tablet',
  'reception-desk': 'desk_triple',
  lighting: 'gadget_a', // weak: no lighting-fixture prop exists
  chair: 'desk_single', // weak: no standalone chair prop, reuses desk
  'coffee-machine': 'gadget_b', // weak: no appliance prop exists
  printer: 'gadget_c', // weak: no printer prop exists
  // cabinet, door, plants, window: no reasonable prop match found,
  // left unmapped (falls back to a coloured placeholder).
}

/** Backend `decoration.<name>` (stripped of the "decoration." prefix)
 * -> frontend `decorations` key. */
export const DECORATION_ASSET_TO_KEY: Record<string, string> = {
  'reception-signage': 'led_sign_a', // exact
  'wall-poster-brainai-logo': 'statue_brain', // brand match
  'potted-plant-decorative': 'bush_b',
  'award-plaque': 'statue_creator', // weak
  'coffee-table': 'bench', // weak
  // bookshelf-slim, rug-modern, wall-clock: no reasonable match found,
  // left unmapped.
}

/** Split "furniture.desk" / "decoration.wall-clock" into
 * `{category, name}`, or null for anything else (e.g. a floor command,
 * which never carries an assetId at all — see the module docstring). */
function splitAssetId(assetId: string | null | undefined): { category: string; name: string } | null {
  if (!assetId) return null
  const dot = assetId.indexOf('.')
  if (dot === -1) return null
  return { category: assetId.slice(0, dot), name: assetId.slice(dot + 1) }
}

export type ResolvedPropAsset = { kind: 'props' | 'decorations'; name: string }

/** Resolve a RenderCommand.assetId (furniture/decoration layer only)
 * to a frontend AssetRegistry lookup, or null if there's no mapping
 * (caller should fall back to its own placeholder in that case). */
export function resolvePropAssetId(assetId: string | null | undefined): ResolvedPropAsset | null {
  const split = splitAssetId(assetId)
  if (!split) return null
  if (split.category === 'furniture') {
    const name = FURNITURE_ASSET_TO_PROP[split.name]
    return name ? { kind: 'props', name } : null
  }
  if (split.category === 'decoration') {
    const name = DECORATION_ASSET_TO_KEY[split.name]
    return name ? { kind: 'decorations', name } : null
  }
  return null
}
