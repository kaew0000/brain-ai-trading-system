# Asset Pipeline — Phase W6

Status: implemented. Metadata and registry only — no binary sprite/tile/
audio files ship in this repository yet, and no renderer is chosen (that is
Phase W5, still outstanding — see "Sequencing note" below).

## What this phase built

1. **Asset Registry** (`world/frontend/asset_loader/asset_registry.py`,
   Phase W3) — unchanged. `AssetRegistry.resolve(asset_id)` dispatches to
   whichever registered `AssetLoader` claims the id.
2. **Four concrete `AssetLoader`s** (`world/frontend/asset_loader/sources/`)
   — one per `AssetSource`: `OpenGameArtLoader`, `LPCLoader`, `KenneyLoader`,
   `CustomLoader`. All four share one implementation
   (`sources/base.py:ManifestBackedAssetLoader`) that reads
   `world/data/assets/asset_manifest.json` and filters by `source`.
3. **`registry_factory.build_default_registry()`** — wires all four loaders
   into one `AssetRegistry` in one call.
4. **Asset Manifest** (`world/data/assets/asset_manifest.json`) — the single
   registry of every asset id used anywhere in the World: 80 character
   sprites (16 characters × 5 animation states), 15 furniture types, 8
   decoration types. Each entry carries `category`, `source`, `tags`,
   `variants`, `dependencies`, `version`, and `compatibleWith`.
5. **Asset Packs** (`world/data/assets/asset_packs.json`) — named groupings
   per source (e.g. `pack.lpc-character-sprites-v1`), for a future loader to
   fetch/cache as a unit.
6. **Compatibility layer** (`world/frontend/asset_loader/compatibility.py`)
   — `is_compatible(entry, engine)` / `unknown_engines(entry)` interpret each
   entry's `compatibleWith` list against the five engines named in
   `world/WORLD.md` (React, PixiJS, Phaser, Godot, Unity). An empty or
   missing list means "no constraint yet."
7. **Validation** (`world/scripts/validate_assets.py`) — no duplicate ids,
   no missing dependencies, no orphan/missing rooms, no orphan/missing
   characters, all cross-references resolve. Runnable standalone or via
   `world/tests/`.

## Why loaders return metadata, not pixels

`AssetLoader.load()` is typed to return `Any` specifically so the "engine-
native handle" can be whatever a concrete renderer needs. Since no renderer
exists yet and no binary asset files ship in this repo, that handle is
currently the asset's own manifest entry — everything a future renderer
needs (source, tags, dependencies, version, compatible engines) to actually
fetch and draw the real file later. This keeps Phase W6 fully testable and
engine-neutral without inventing pixel data or a specific file layout ahead
of the Phase W5 renderer decision.

## Supported sources

| Source | Used for | Notes |
|---|---|---|
| LPC (Liberated Pixel Cup) | Character sprites | Matches `world/docs/asset-conventions.md` (LPC equipment slots, standard animation states) |
| Kenney | Furniture | Desk, Chair, Whiteboard, Meeting Table, Reception Desk, Coffee Machine, Printer, Cabinet, Door, Window, Lighting, and 3 decorations |
| OpenGameArt | Furniture (Monitor, Laptop, Server Rack) + 2 decorations | Modern-office-only per `WORLD_OFFICE_POLICY.md` |
| Custom | Brand-specific decorations (logo poster, award plaque, reception signage) | Brain AI-specific, not from a third-party pack |

Adding a fifth source means: implement one `AssetLoader` subclass, register
it in `registry_factory.py`. No other file changes.

## Asset dependency diagram (example edges)

```
furniture.reception-desk  ──depends on──▶  furniture.monitor
furniture.meeting-table   ──depends on──▶  furniture.chair
decoration.coffee-table   ──depends on──▶  furniture.chair
```

All other manifest entries currently have no dependencies. Every dependency
edge is validated to resolve to a real manifest id (see
`world/scripts/validate_assets.py`).

## Asset loading policy

- **Resolution:** `AssetRegistry.resolve(id)` checks its cache first, then
  asks each registered loader `can_load(id)` in registration order, caches
  the first match.
- **Failure:** an id no loader claims raises `UnresolvedAssetError` — no
  silent fallback to a placeholder asset.
- **Versioning:** every manifest entry has a semver `version` string. No
  version-resolution logic exists yet (single version per id); this is
  reserved for a future phase if multiple versions of the same asset need
  to coexist.

## Sequencing note (documented per Krush's decision)

The repo's own roadmap originally ordered asset-pipeline activation as
**Phase W6**, after **W4** (read-only ingestion adapter) and **W5** (pick a
renderer). This phase was built now, ahead of W4/W5, because it is
metadata-only and has no dependency on either — Krush confirmed proceeding
under the existing W6 label rather than renumbering. W4 and W5 remain
outstanding and are unaffected by this work.
