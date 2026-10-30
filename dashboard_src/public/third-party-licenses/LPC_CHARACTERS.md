# Office World character sheets (V16 §93)

`assets/world/lpc/*.png` are 10 character sheets exported from the Universal LPC Spritesheet Character Generator
(https://liberatedpixelcup.github.io/Universal-LPC-Spritesheet-Character-Generator/). They are third-party, layered art.

- Per-layer authors, source URLs and licences: `lpc_credits.csv` (merged and de-duplicated from the generator's own `credits*.csv`).
- The layers are licensed under a mix of CC0, OGA-BY 3.0, CC-BY 3.0+, CC-BY-SA 3.0 and GPL 2.0/3.0 (the generator's "enabled licenses" were
  CC0, CC-BY-SA, CC-BY, OGA-BY and GPL). Attribution to the listed authors is required; CC-BY-SA layers carry share-alike terms.
- Keep `lpc_credits.csv` with the sheets whenever they are redistributed. The project owner states personal use; if the repository or a build is
  published, review the licence terms of the layers in `lpc_credits.csv` first.
- Re-import with `python -m world.scripts.import_lpc_characters <dir-or-zip>` (see the script docstring).
- Separate from `ISO_ASSETS.md`, which covers the generated isometric art (no third-party content).
