"""Tile — a value object describing one floor/background grid cell.
Pure data; drawing is `TileRenderer`'s job."""

from dataclasses import dataclass


@dataclass
class Tile:
    tile_id: str
    asset_id: str
    grid_x: int
    grid_y: int
