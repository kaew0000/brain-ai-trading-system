// ============================================================
// Brain Bot V15 — Tileset Packer
// AssetRegistry loads every ground/road/water PNG as its own
// separate Phaser texture. Phaser.Tilemaps needs one sliced
// tileset IMAGE (grid of equally-sized cells) to index tiles by
// number. This packer draws N already-loaded textures onto one
// offscreen canvas at tileSize-aligned slots and registers the
// result as a new Phaser texture, which is then used as the
// tileset image for map.addTilesetImage().
//
// Tile 0 is reserved (Tiled convention: 0 = "no tile").
// ============================================================

import Phaser from 'phaser';

export interface PackedTileset {
  /** Phaser texture key of the generated atlas image */
  textureKey: string;
  /** tile name -> 1-based tile id (Tiled GID, before firstgid offset) */
  idByName: Map<string, number>;
  /** ordered list of names, index 0 unused (matches idByName ids) */
  names: string[];
  columns: number;
  rows: number;
  tileSize: number;
}

/**
 * Pack a list of already-registered Phaser texture keys into one
 * tileset atlas. Each entry is { name, textureKey } where textureKey
 * must already exist in scene.textures (loaded via AssetRegistry).
 */
export function packTileset(
  scene: Phaser.Scene,
  atlasKey: string,
  tileSize: number,
  entries: Array<{ name: string; textureKey: string }>,
): PackedTileset {
  if (scene.textures.exists(atlasKey)) {
    scene.textures.remove(atlasKey);
  }

  // Atlas layout: gid 0 always means "no tile" in Tiled/Phaser and is never
  // rendered, so the atlas image itself only needs one cell per real entry —
  // no reserved blank cell. Phaser looks up a tile at
  // localIndex = gid - tileset.firstgid; since every packed tileset here uses
  // firstgid = 1, localIndex = gid - 1 = the entry's array index `i`. Packing
  // MUST use that same `i`-based position, or every cell ends up one slot
  // away from where Phaser actually samples it (this was the bug: cells were
  // previously packed at position `id` = i+1 instead of `i`, so gid 1 pointed
  // at a never-drawn cell — rendering fully transparent/black — and every
  // other gid sampled its *neighbour's* image instead of its own).
  const count = entries.length;
  const columns = Math.ceil(Math.sqrt(count));
  const rows = Math.ceil(count / columns);

  const canvasTex = scene.textures.createCanvas(
    atlasKey,
    columns * tileSize,
    rows * tileSize,
  )!;
  const ctx = canvasTex.getContext();

  const idByName = new Map<string, number>();
  const names: string[] = ['__empty__'];

  entries.forEach((entry, i) => {
    const id = i + 1; // the gid used in layer data (firstgid=1 + localIndex i)
    idByName.set(entry.name, id);
    names[id] = entry.name;

    // Local atlas cell position — must match Phaser's own
    // (gid - firstgid) = i, NOT the gid itself.
    const col = i % columns;
    const row = Math.floor(i / columns);
    const dx = col * tileSize;
    const dy = row * tileSize;

    if (!scene.textures.exists(entry.textureKey)) return;
    const src = scene.textures.get(entry.textureKey).getSourceImage() as
      | HTMLImageElement
      | HTMLCanvasElement;
    if (!src || !('width' in src) || src.width === 0) return;

    // Draw scaled-to-fit into the tileSize x tileSize cell, centered.
    const scale = Math.min(tileSize / src.width, tileSize / src.height);
    const w = src.width * scale;
    const h = src.height * scale;
    const ox = dx + (tileSize - w) / 2;
    const oy = dy + (tileSize - h);
    ctx.drawImage(src as CanvasImageSource, ox, oy, w, h);
  });

  canvasTex.refresh();

  return { textureKey: atlasKey, idByName, names, columns, rows, tileSize };
}
