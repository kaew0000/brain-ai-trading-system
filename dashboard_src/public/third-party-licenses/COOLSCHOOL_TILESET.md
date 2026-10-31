# Office World tile map art (V16 §94)

`assets/world/tile/atlas.png` is cut from the **CoolSchool tileset (48 px)** by NettySvit, bundled in the supplied
`game_asset.zip` under `office_assets/CoolSchool_tileset_48px/`. It is licensed **CC0 1.0**
(https://creativecommons.org/publicdomain/zero/1.0/): copy, modify and redistribute, including commercially, without
asking. Credit to the artist is appreciated but not required.

- Source sheet (unmodified): `world/data/assets/source/CoolSchool_tileset.png`.
- Floor colour variants are the source floor tile with its hue shifted by `world/scripts/build_tile_world.py`.
- Rebuild: `python -m world.scripts.build_tile_world` (layout and sprite crops live in `world/data/assets/tile_world.json`).
