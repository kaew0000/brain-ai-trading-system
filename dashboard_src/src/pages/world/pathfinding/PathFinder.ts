// ============================================================
// Brain Bot V15 — A* Pathfinder
// Simple binary-heap-free A* over the walkable tile grid.
// Used for mouse click-to-move so the player routes around
// walls/water instead of just walking in a straight line.
// Grid is small (120x72 = 8640 tiles) so a plain array-based
// open set is fast enough at interactive rates.
// ============================================================

import { isBlocking } from '../MapLoader';
import type { TileType } from '../types/world.types';

interface PathNode {
  tx: number;
  ty: number;
  g: number;
  f: number;
  parent: PathNode | null;
}

const NEIGHBORS_4 = [
  [0, -1], [0, 1], [-1, 0], [1, 0],
];

function heuristic(ax: number, ay: number, bx: number, by: number): number {
  return Math.abs(ax - bx) + Math.abs(ay - by);
}

/**
 * Find a walkable path from (sx,sy) to (tx,ty) on the tile grid.
 * Returns a list of {tx,ty} waypoints (excluding the start tile),
 * or null if unreachable / target blocked.
 */
export function findPath(
  tiles: TileType[][],
  cols: number,
  rows: number,
  sx: number,
  sy: number,
  tx: number,
  ty: number,
  maxIterations = 4000,
): Array<{ tx: number; ty: number }> | null {
  if (tx < 0 || tx >= cols || ty < 0 || ty >= rows) return null;
  if (isBlocking(tiles[ty]?.[tx] ?? 'void')) return null;
  if (sx === tx && sy === ty) return [];

  const key = (x: number, y: number) => y * cols + x;

  const open = new Map<number, PathNode>();
  const closed = new Set<number>();

  const start: PathNode = { tx: sx, ty: sy, g: 0, f: heuristic(sx, sy, tx, ty), parent: null };
  open.set(key(sx, sy), start);

  let iterations = 0;

  while (open.size > 0) {
    if (++iterations > maxIterations) return null; // safety bound

    // Pick lowest-f node (linear scan; grid is small enough)
    let current: PathNode | null = null;
    let currentKey = -1;
    for (const [k, node] of open) {
      if (!current || node.f < current.f) {
        current = node;
        currentKey = k;
      }
    }
    if (!current) break;

    if (current.tx === tx && current.ty === ty) {
      // Reconstruct path
      const path: Array<{ tx: number; ty: number }> = [];
      let n: PathNode | null = current;
      while (n && n.parent) {
        path.unshift({ tx: n.tx, ty: n.ty });
        n = n.parent;
      }
      return path;
    }

    open.delete(currentKey);
    closed.add(currentKey);

    for (const [dx, dy] of NEIGHBORS_4) {
      const nx = current.tx + dx;
      const ny = current.ty + dy;
      if (nx < 0 || nx >= cols || ny < 0 || ny >= rows) continue;
      const nk = key(nx, ny);
      if (closed.has(nk)) continue;
      if (isBlocking(tiles[ny]?.[nx] ?? 'void')) continue;

      const g = current.g + 1;
      const existing = open.get(nk);
      if (!existing || g < existing.g) {
        open.set(nk, {
          tx: nx, ty: ny, g,
          f: g + heuristic(nx, ny, tx, ty),
          parent: current,
        });
      }
    }
  }

  return null; // no path found
}

/** Simplify a waypoint path by collapsing straight runs into fewer points. */
export function simplifyPath(
  path: Array<{ tx: number; ty: number }>,
): Array<{ tx: number; ty: number }> {
  if (path.length <= 2) return path;
  const out: Array<{ tx: number; ty: number }> = [path[0]];
  let prevDx = path[1].tx - path[0].tx;
  let prevDy = path[1].ty - path[0].ty;
  for (let i = 1; i < path.length - 1; i++) {
    const dx = path[i + 1].tx - path[i].tx;
    const dy = path[i + 1].ty - path[i].ty;
    if (dx !== prevDx || dy !== prevDy) {
      out.push(path[i]);
      prevDx = dx; prevDy = dy;
    }
  }
  out.push(path[path.length - 1]);
  return out;
}
