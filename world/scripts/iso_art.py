"""Drawing primitives for the Office World isometric art (W-ISO-3).

Pure Pillow drawing code - deterministic, no randomness, no network, no
third-party art. ``generate_iso_assets.py`` owns the spec/manifest/output
plumbing and delegates all pixel work to this module.

Visual target: a bright, readable "DeskRPG-style" isometric office -
light tiled floor, glass partitions, desks with monitors and blue dividers,
swivel chairs, plants, wall boards - and small outlined chibi workers.
(DeskRPG was a UX reference only; nothing is copied from it.)
"""

from __future__ import annotations

from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFilter

RGB = tuple[int, int, int]

OUTLINE = (24, 28, 40)
SCREEN_ON = (56, 189, 248)
SCREEN_BG = (15, 23, 42)
BLUE_PANEL = (59, 108, 160)

#: Walk-sheet layout: one row per direction, one column per frame.
WALK_DIRECTIONS = ("se", "sw", "nw", "ne")
WALK_FRAMES = 4


def rgb(hex_color: str) -> RGB:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def shade(c: RGB, f: float) -> RGB:
    return tuple(max(0, min(255, int(v * f))) for v in c)  # type: ignore[return-value]


def mix(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))  # type: ignore[return-value]


# --------------------------------------------------------------------------
# Isometric box canvas
# --------------------------------------------------------------------------


class IsoCanvas:
    """Axis-aligned boxes in a footprint-local grid (units = tiles, z = px).

    Viewer looks from +x/+y: the visible faces are the y1 plane (lower-left),
    the x1 plane (lower-right) and the top. Draw back-to-front (small x+y first).
    """

    def __init__(self, spec: dict[str, Any], footprint: tuple[int, int], height: int) -> None:
        self.ss = int(spec["supersample"])
        self.tw = spec["tile"]["width"]
        self.th = spec["tile"]["height"]
        margin = int(spec["propMargin"])
        self.a, self.b = footprint
        self.w = int((self.a + self.b) * self.tw / 2) + 2 * margin
        self.h = int((self.a + self.b) * self.th / 2) + height + 2 * margin
        self.ox = self.b * self.tw / 2 + margin
        self.oy = height + margin
        self.img = Image.new("RGBA", (self.w * self.ss, self.h * self.ss), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    # -- geometry ---------------------------------------------------------
    def pt(self, gx: float, gy: float, z: float = 0.0) -> tuple[float, float]:
        sx = (gx - gy) * self.tw / 2 + self.ox
        sy = (gx + gy) * self.th / 2 + self.oy - z
        return sx * self.ss, sy * self.ss

    def _poly(self, pts: list[tuple[float, float]], fill: RGB, edge: RGB | None = None) -> None:
        self.d.polygon(pts, fill=fill)
        if edge is not None:
            self.d.line(pts + [pts[0]], fill=edge, width=max(1, int(self.ss * 0.7)))

    # -- solids -----------------------------------------------------------
    def box(self, x0: float, y0: float, x1: float, y1: float, z0: float, z1: float,
            color: RGB, front: RGB | None = None, right: RGB | None = None,
            edge: bool = True) -> None:
        e = shade(color, 0.5) if edge else None
        left = [self.pt(x0, y1, z0), self.pt(x1, y1, z0), self.pt(x1, y1, z1), self.pt(x0, y1, z1)]
        rgt = [self.pt(x1, y1, z0), self.pt(x1, y0, z0), self.pt(x1, y0, z1), self.pt(x1, y1, z1)]
        top = [self.pt(x0, y0, z1), self.pt(x1, y0, z1), self.pt(x1, y1, z1), self.pt(x0, y1, z1)]
        self._poly(left, front or shade(color, 0.82), e)
        self._poly(rgt, right or shade(color, 0.62), e)
        self._poly(top, shade(color, 1.08), e)

    def quad_y(self, x0: float, x1: float, y: float, z0: float, z1: float, fill: RGB) -> None:
        """Rectangle painted on a y-plane (faces the lower-left)."""
        self.d.polygon([self.pt(x0, y, z0), self.pt(x1, y, z0), self.pt(x1, y, z1), self.pt(x0, y, z1)], fill=fill)

    def quad_x(self, y0: float, y1: float, x: float, z0: float, z1: float, fill: RGB) -> None:
        """Rectangle painted on an x-plane (faces the lower-right)."""
        self.d.polygon([self.pt(x, y0, z0), self.pt(x, y1, z0), self.pt(x, y1, z1), self.pt(x, y0, z1)], fill=fill)

    def line(self, p0: tuple[float, float, float], p1: tuple[float, float, float], fill: RGB, width: float = 1.0) -> None:
        self.d.line([self.pt(*p0), self.pt(*p1)], fill=fill, width=max(1, int(width * self.ss)))

    def ellipse(self, gx: float, gy: float, z: float, rx: float, ry: float, color: RGB) -> None:
        cx, cy = self.pt(gx, gy, z)
        self.d.ellipse([cx - rx * self.ss, cy - ry * self.ss, cx + rx * self.ss, cy + ry * self.ss],
                       fill=color, outline=shade(color, 0.5), width=max(1, int(self.ss * 0.6)))

    def glass_y(self, x0: float, x1: float, y: float, z0: float, z1: float, rgba: tuple[int, int, int, int]) -> None:
        self._glass([self.pt(x0, y, z0), self.pt(x1, y, z0), self.pt(x1, y, z1), self.pt(x0, y, z1)], rgba)

    def glass_x(self, y0: float, y1: float, x: float, z0: float, z1: float, rgba: tuple[int, int, int, int]) -> None:
        self._glass([self.pt(x, y0, z0), self.pt(x, y1, z0), self.pt(x, y1, z1), self.pt(x, y0, z1)], rgba)

    def _glass(self, pts: list[tuple[float, float]], rgba: tuple[int, int, int, int]) -> None:
        layer = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.polygon(pts, fill=rgba)
        ld.line(pts + [pts[0]], fill=(rgba[0], rgba[1], rgba[2], min(255, rgba[3] + 110)), width=max(1, int(self.ss * 0.7)))
        self.img = Image.alpha_composite(self.img, layer)
        self.d = ImageDraw.Draw(self.img)

    def finish(self) -> Image.Image:
        return self.img.resize((self.w, self.h), Image.LANCZOS)

    def anchor(self) -> list[float]:
        ax, ay = self.pt(self.a / 2, self.b / 2, 0.0)
        return [round(ax / self.ss / self.w, 4), round(ay / self.ss / self.h, 4)]


# --------------------------------------------------------------------------
# Prop parts
# --------------------------------------------------------------------------


def _monitor(c: IsoCanvas, x: float, y: float, z: float, w: float, facing_front: bool, glow: RGB = SCREEN_ON) -> None:
    """Monitor centred on x, back edge at y. Facing the viewer shows the lit screen."""
    c.box(x - 0.12, y + 0.02, x + 0.12, y + 0.22, z, z + 1.6, (40, 46, 58))  # foot
    c.box(x - 0.04, y + 0.08, x + 0.04, y + 0.16, z + 1.6, z + 7, (52, 58, 72))  # neck
    x0, x1 = x - w / 2, x + w / 2
    c.box(x0, y, x1, y + 0.1, z + 7, z + 7 + 13, (36, 42, 54), front=(30, 36, 48))
    if facing_front:
        y_face = y + 0.1
        c.quad_y(x0 + 0.04, x1 - 0.04, y_face, z + 8.4, z + 7 + 11.6, SCREEN_BG)
        # simple chart: three bars + a trend line so screens read as "trading terminal"
        span = (x1 - x0 - 0.12)
        for i, hgt in enumerate((2.6, 4.4, 3.4, 5.6)):
            bx = x0 + 0.08 + span * (0.12 + i * 0.22)
            c.quad_y(bx, bx + span * 0.12, y_face, z + 9, z + 9 + hgt, mix(glow, SCREEN_BG, 0.15 * (i % 2)))
        c.line((x0 + 0.08, y_face, z + 14.2), (x1 - 0.08, y_face, z + 16.8), (167, 243, 208), 0.9)


def _keyboard(c: IsoCanvas, x: float, y: float, z: float) -> None:
    c.box(x - 0.28, y, x + 0.28, y + 0.2, z, z + 1.2, (226, 232, 240), edge=False)
    c.box(x + 0.36, y + 0.04, x + 0.46, y + 0.16, z, z + 1.0, (203, 213, 225), edge=False)


def _desk_body(c: IsoCanvas, x0: float, x1: float, y0: float, y1: float, top_z: float, col: RGB) -> None:
    leg = shade(col, 0.72)
    c.box(x0 + 0.04, y0 + 0.08, x0 + 0.14, y1 - 0.08, 0, top_z - 3, leg)  # left panel
    c.box(x0 + 0.14, y0 + 0.1, x1 - 0.14, y0 + 0.2, top_z - 13, top_z - 3, shade(col, 0.78))  # modesty panel
    c.box(x1 - 0.14, y0 + 0.08, x1 - 0.04, y1 - 0.08, 0, top_z - 3, leg)  # right panel
    c.box(x0, y0, x1, y1, top_z - 3, top_z, col)  # top slab


# --------------------------------------------------------------------------
# Props
# --------------------------------------------------------------------------

PropFn = Callable[[IsoCanvas, int, int, int, RGB, RGB], None]


def _p_desk(c: IsoCanvas, a: int, b: int, h: int, col: RGB, acc: RGB) -> None:
    _desk_body(c, 0, a, 0, b, h, col)


def _p_workstation(c: IsoCanvas, a: int, b: int, h: int, col: RGB, acc: RGB) -> None:
    top = 22
    _desk_body(c, 0, a, 0, b, top, col)
    c.box(0.0, 0.0, a, 0.1, top, top + 15, BLUE_PANEL, front=shade(BLUE_PANEL, 0.9))  # blue divider
    for i in range(a):
        _monitor(c, i + 0.5, 0.14, top, 0.82, True)
        _keyboard(c, i + 0.5, 0.58, top)
    c.box(a - 0.38, 0.42, a - 0.14, 0.62, top, top + 3, (248, 250, 252))  # paper stack / mug


def _p_cluster(c: IsoCanvas, a: int, b: int, h: int, col: RGB, acc: RGB) -> None:
    """Two rows of desks back to back with a centre divider (the DeskRPG pod look)."""
    top = 22
    mid = b / 2
    _desk_body(c, 0, a, 0, mid - 0.05, top, col)  # back row (we see monitor backs)
    for i in range(a):
        _monitor(c, i + 0.5, 0.28, top, 0.82, False)
        _keyboard(c, i + 0.5, 0.02, top)
    c.box(0.0, mid - 0.06, a, mid + 0.06, top, top + 15, BLUE_PANEL, front=shade(BLUE_PANEL, 0.9))
    _desk_body(c, 0, a, mid + 0.05, b, top, col)  # front row (we see lit screens)
    for i in range(a):
        _monitor(c, i + 0.5, mid + 0.16, top, 0.82, True)
        _keyboard(c, i + 0.5, mid + 0.6, top)


def _p_chair(c: IsoCanvas, a: int, b: int, h: int, col: RGB, acc: RGB) -> None:
    for cx, cy in ((0.2, 0.2), (0.8, 0.2), (0.2, 0.8), (0.8, 0.8), (0.5, 0.5)):  # five-star base casters
        c.box(cx - 0.05, cy - 0.05, cx + 0.05, cy + 0.05, 0, 2, (30, 34, 44), edge=False)
    c.box(0.18, 0.18, 0.82, 0.82, 1.5, 3, shade(acc, 0.8), edge=False)
    c.box(0.44, 0.44, 0.56, 0.56, 3, 12, (70, 76, 90))  # gas lift
    c.box(0.15, 0.15, 0.85, 0.85, 12, 17, col)  # seat
    c.box(0.18, 0.1, 0.82, 0.24, 17, h, col)  # backrest
    c.box(0.18, 0.1, 0.82, 0.14, 19, h - 2, shade(col, 1.25), edge=False)  # backrest highlight


def _p_monitor(c: IsoCanvas, a: int, b: int, h: int, col: RGB, acc: RGB) -> None:
    _monitor(c, 0.5, 0.35, 0, 0.84, True, acc)


def _p_table(c: IsoCanvas, a: int, b: int, h: int, col: RGB, acc: RGB) -> None:
    c.box(a / 2 - 0.35, b / 2 - 0.35, a / 2 + 0.35, b / 2 + 0.35, 0, h - 3, acc)
    c.box(0.1, 0.1, a - 0.1, b - 0.1, h - 3, h, col)
    c.box(a / 2 - 0.5, b / 2 - 0.22, a / 2 + 0.5, b / 2 + 0.22, h, h + 0.8, shade(col, 1.12), edge=False)  # inlay
    c.box(a / 2 + 0.55, b / 2 - 0.12, a / 2 + 0.85, b / 2 + 0.12, h, h + 2.2, (241, 245, 249))  # notepad / tablet


def _p_rack(c: IsoCanvas, a: int, b: int, h: int, col: RGB, acc: RGB) -> None:
    c.box(0.1, 0.1, 0.9, 0.9, 0, h, col)
    for i in range(6):  # blade faces + status LEDs on the front-left face
        z = 6 + i * 9
        c.quad_y(0.16, 0.84, 0.9, z, z + 7, shade(col, 1.5 if i % 2 else 1.25))
        lx, ly = c.pt(0.2, 0.9, z + 3.5)
        c.d.rectangle([lx, ly - 1.2 * c.ss, lx + 4 * c.ss, ly + 1.2 * c.ss], fill=acc if i % 3 else shade(acc, 0.5))
        lx2, ly2 = c.pt(0.4, 0.9, z + 3.5)
        c.d.rectangle([lx2, ly2 - 1.2 * c.ss, lx2 + 3 * c.ss, ly2 + 1.2 * c.ss], fill=(74, 222, 128) if i % 2 else (250, 204, 21))


def _p_plant(c: IsoCanvas, a: int, b: int, h: int, col: RGB, acc: RGB) -> None:
    c.box(0.3, 0.3, 0.7, 0.7, 0, 13, col)  # pot
    c.box(0.28, 0.28, 0.72, 0.72, 11, 13, shade(col, 1.2), edge=False)  # rim
    c.box(0.34, 0.34, 0.66, 0.66, 13, 14, (92, 64, 40), edge=False)  # soil
    leaves = ((0.5, 0.5, 30, 12), (0.38, 0.55, 25, 9), (0.64, 0.45, 27, 9), (0.5, 0.5, 40, 8), (0.42, 0.42, 36, 7), (0.6, 0.6, 22, 8))
    for i, (dx, dy, z, r) in enumerate(leaves):
        c.ellipse(dx, dy, z, r, r * 0.9, shade(acc, 0.72 + 0.1 * (i % 4)))


def _p_plant_large(c: IsoCanvas, a: int, b: int, h: int, col: RGB, acc: RGB) -> None:
    c.box(0.25, 0.25, 0.75, 0.75, 0, 16, col)
    c.box(0.23, 0.23, 0.77, 0.77, 14, 16, shade(col, 1.2), edge=False)
    c.box(0.46, 0.46, 0.54, 0.54, 16, 34, (101, 74, 48))  # trunk
    for i, (dx, dy, z, r) in enumerate(((0.5, 0.5, 46, 13), (0.34, 0.5, 40, 10), (0.66, 0.5, 42, 10), (0.5, 0.35, 52, 9), (0.5, 0.65, 38, 10), (0.5, 0.5, 58, 8))):
        c.ellipse(dx, dy, z, r, r * 0.92, shade(acc, 0.7 + 0.1 * (i % 4)))


def _p_partition(c: IsoCanvas, a: int, b: int, h: int, col: RGB, acc: RGB) -> None:
    c.box(0, b / 2 - 0.08, a, b / 2 + 0.08, 0, h, col)
    c.box(0, b / 2 - 0.1, a, b / 2 + 0.1, h - 3, h, acc)


def _p_sofa(c: IsoCanvas, a: int, b: int, h: int, col: RGB, acc: RGB) -> None:
    c.box(0, 0.2, a, 1.0, 0, 12, col)
    c.box(0, 0.2, a, 0.45, 12, h, col)
    c.box(0, 0.45, 0.22, 1.0, 12, 20, shade(col, 0.9))
    c.box(a - 0.22, 0.45, a, 1.0, 12, 20, shade(col, 0.9))
    for i in range(a):  # seat cushions
        c.box(0.24 + i * (a - 0.48) / a, 0.5, 0.24 + (i + 1) * (a - 0.48) / a - 0.04, 0.95, 12, 15, shade(col, 1.18), edge=False)


def _p_glass_wall(c: IsoCanvas, a: int, b: int, h: int, col: RGB, acc: RGB) -> None:
    """Glass partition. a>b runs along x; b>a runs along y. ``col`` = frame, ``acc`` = glass tint."""
    glass = (acc[0], acc[1], acc[2], 62)
    if a >= b:
        y = b / 2
        c.box(0, y - 0.05, 0.1, y + 0.05, 0, h, col)  # back post
        c.box(0, y - 0.05, a, y + 0.05, 0, 5, shade(col, 0.9))  # kick plate
        c.glass_y(0.1, a - 0.1, y + 0.05, 5, h - 3, glass)
        c.glass_y(0.1, a - 0.1, y - 0.05, 5, h - 3, glass)
        for i in range(1, a):  # mullions
            c.box(i - 0.04, y - 0.05, i + 0.04, y + 0.05, 5, h - 3, shade(col, 1.2), edge=False)
        c.box(0, y - 0.06, a, y + 0.06, h - 3, h, col)  # top rail
        c.box(a - 0.1, y - 0.05, a, y + 0.05, 0, h, col)  # front post
        c.line((0.4, y + 0.06, h - 12), (0.9, y + 0.06, h - 5), (255, 255, 255), 0.8)  # glare streak
    else:
        x = a / 2
        c.box(x - 0.05, 0, x + 0.05, 0.1, 0, h, col)
        c.box(x - 0.05, 0, x + 0.05, b, 0, 5, shade(col, 0.9))
        c.glass_x(0.1, b - 0.1, x - 0.05, 5, h - 3, glass)
        c.glass_x(0.1, b - 0.1, x + 0.05, 5, h - 3, glass)
        for i in range(1, b):
            c.box(x - 0.05, i - 0.04, x + 0.05, i + 0.04, 5, h - 3, shade(col, 1.2), edge=False)
        c.box(x - 0.06, 0, x + 0.06, b, h - 3, h, col)
        c.box(x - 0.05, b - 0.1, x + 0.05, b, 0, h, col)
        c.line((x + 0.06, 0.4, h - 12), (x + 0.06, 0.9, h - 5), (255, 255, 255), 0.8)


def _p_whiteboard(c: IsoCanvas, a: int, b: int, h: int, col: RGB, acc: RGB) -> None:
    """Standing board on an easel frame; face toward the lower-left."""
    y = b / 2
    c.box(0.15, y - 0.05, 0.25, y + 0.05, 0, 14, (90, 96, 110))
    c.box(a - 0.25, y - 0.05, a - 0.15, y + 0.05, 0, 14, (90, 96, 110))
    c.box(0.05, y - 0.06, a - 0.05, y + 0.06, 14, h, col)  # frame
    c.quad_y(0.14, a - 0.14, y + 0.06, 18, h - 4, (248, 250, 252))
    for i in range(4):  # scribbled bullet lines
        zz = h - 9 - i * 6
        c.line((0.3, y + 0.06, zz), (0.3 + (0.9 if i % 2 else 1.2) * (a / 2), y + 0.06, zz), acc if i == 0 else (148, 163, 184), 1.0)
    c.line((a - 0.5, y + 0.06, 22), (a - 0.35, y + 0.06, 30), (239, 68, 68), 1.2)


def _p_bookshelf(c: IsoCanvas, a: int, b: int, h: int, col: RGB, acc: RGB) -> None:
    c.box(0.05, 0.15, a - 0.05, b - 0.15, 0, h, col)
    y = b - 0.15
    palette = ((239, 68, 68), (59, 130, 246), (250, 204, 21), (34, 197, 94), (168, 85, 247), (249, 115, 22))
    for row in range(3):
        z0 = 4 + row * 15
        c.quad_y(0.12, a - 0.12, y, z0, z0 + 12, shade(col, 0.45))
        n = a * 6
        for i in range(n):
            bx = 0.14 + i * (a - 0.28) / n
            bh = 8 + (i * 5 + row * 3) % 4
            c.quad_y(bx, bx + (a - 0.28) / n * 0.8, y, z0, z0 + bh, palette[(i + row * 2) % len(palette)])
    c.box(0.0, 0.1, a, b - 0.1, h - 2, h, shade(col, 1.15))


def _p_coffee(c: IsoCanvas, a: int, b: int, h: int, col: RGB, acc: RGB) -> None:
    c.box(0.15, 0.15, 0.85, 0.85, 0, 14, (120, 90, 64))  # counter
    c.box(0.22, 0.22, 0.78, 0.7, 14, h, col)  # machine body
    c.quad_y(0.3, 0.7, 0.7, h - 12, h - 4, shade(acc, 0.9))  # display
    c.box(0.42, 0.55, 0.58, 0.68, 14, 20, (241, 245, 249))  # cup


def _p_cooler(c: IsoCanvas, a: int, b: int, h: int, col: RGB, acc: RGB) -> None:
    c.box(0.25, 0.25, 0.75, 0.75, 0, h - 14, col)
    c.box(0.32, 0.32, 0.68, 0.68, h - 14, h, (147, 197, 253), front=(125, 180, 245))  # water jug
    c.box(0.4, 0.74, 0.5, 0.8, 14, 17, (239, 68, 68), edge=False)
    c.box(0.5, 0.74, 0.6, 0.8, 14, 17, (59, 130, 246), edge=False)


def _p_printer(c: IsoCanvas, a: int, b: int, h: int, col: RGB, acc: RGB) -> None:
    c.box(0.12, 0.12, 0.88, 0.88, 0, 10, shade(col, 0.9))  # stand
    c.box(0.1, 0.15, 0.9, 0.85, 10, h, col)
    c.box(0.2, 0.2, 0.8, 0.5, h, h + 2, (248, 250, 252), edge=False)  # paper tray
    c.quad_y(0.5, 0.8, 0.85, 14, 17, acc)


def _p_rug(c: IsoCanvas, a: int, b: int, h: int, col: RGB, acc: RGB) -> None:
    c.box(0.1, 0.1, a - 0.1, b - 0.1, 0, h, col, edge=False)
    c.box(0.3, 0.3, a - 0.3, b - 0.3, h, h + 0.5, acc, edge=False)


def _p_screen(c: IsoCanvas, a: int, b: int, h: int, col: RGB, acc: RGB) -> None:
    """Wall-standing market board with candlesticks (fits the trading-world theme)."""
    y = b / 2
    c.box(0.2, y - 0.05, 0.3, y + 0.05, 0, 14, (60, 66, 80))
    c.box(a - 0.3, y - 0.05, a - 0.2, y + 0.05, 0, 14, (60, 66, 80))
    c.box(0.05, y - 0.07, a - 0.05, y + 0.07, 14, h, col)
    c.quad_y(0.12, a - 0.12, y + 0.07, 18, h - 4, SCREEN_BG)
    n = 9
    for i in range(n):
        x0 = 0.2 + i * (a - 0.4) / n
        up = (i * 7) % 3 != 0
        base = 24 + (i * 5) % 9
        hgt = 4 + (i * 3) % 7
        colr = (74, 222, 128) if up else (248, 113, 113)
        mid = x0 + (a - 0.4) / n * 0.4
        c.line((mid, y + 0.07, base - 2), (mid, y + 0.07, base + hgt + 2), colr, 0.8)
        c.quad_y(x0, x0 + (a - 0.4) / n * 0.8, y + 0.07, base, base + hgt, colr)


PROP_SHAPES: dict[str, PropFn] = {
    "desk": _p_desk, "workstation": _p_workstation, "cluster": _p_cluster, "chair": _p_chair,
    "monitor": _p_monitor, "table": _p_table, "rack": _p_rack, "plant": _p_plant,
    "plant_large": _p_plant_large, "partition": _p_partition, "sofa": _p_sofa,
    "glass_wall": _p_glass_wall, "whiteboard": _p_whiteboard, "bookshelf": _p_bookshelf,
    "coffee": _p_coffee, "cooler": _p_cooler, "printer": _p_printer, "rug": _p_rug,
    "screen": _p_screen,
}


def draw_prop(spec: dict[str, Any], prop: dict[str, Any]) -> tuple[Image.Image, list[float]]:
    a, b = prop["footprint"]
    height = int(prop["height"])
    shape = prop["shape"]
    fn = PROP_SHAPES.get(shape)
    if fn is None:
        raise ValueError(f"unknown prop shape {shape!r} for {prop['key']!r}")
    c = IsoCanvas(spec, (a, b), height)
    fn(c, a, b, height, rgb(prop["color"]), rgb(prop["accent"]))
    return c.finish(), c.anchor()


# --------------------------------------------------------------------------
# Floor tiles (64x32 diamonds)
# --------------------------------------------------------------------------


def draw_tile(spec: dict[str, Any], tile: dict[str, Any]) -> Image.Image:
    ss = 4
    tw, th = spec["tile"]["width"], spec["tile"]["height"]
    img = Image.new("RGBA", (tw * ss, th * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    base, edge = rgb(tile["color"]), rgb(tile["edge"])
    diamond = [(tw / 2 * ss, 0), (tw * ss, th / 2 * ss), (tw / 2 * ss, th * ss), (0, th / 2 * ss)]
    d.polygon(diamond, fill=base)
    kind = tile["pattern"]
    if kind == "wood":
        for i in range(1, 6):  # planks run parallel to the x axis: T-L edge -> R-B edge
            t = i / 6
            s0 = (tw / 2 * (1 - t) * ss, th / 2 * t * ss * 1.0)
            s1 = (s0[0] + tw / 2 * ss, s0[1] + th / 2 * ss)
            d.line([s0, s1], fill=shade(base, 0.84), width=ss)
            mid = ((s0[0] + s1[0]) / 2, (s0[1] + s1[1]) / 2)
            d.line([(mid[0] - 3 * ss, mid[1] - 1.5 * ss), (mid[0] + 3 * ss, mid[1] + 1.5 * ss)], fill=shade(base, 1.06), width=ss // 2 or 1)
    elif kind == "carpet":
        for j in range(0, th * ss, 3 * ss):
            for i in range(0, tw * ss, 3 * ss):
                if (i // ss + j // ss * 2) % 5 == 0:
                    d.point((i + ss, j + ss), fill=shade(base, 0.9))
    # soft bevel: lighter top edges, darker bottom edges
    top_l, top_r = diamond[3], diamond[1]
    d.line([top_l, diamond[0], top_r], fill=mix(base, (255, 255, 255), 0.35), width=ss)
    d.line([top_l, diamond[2], top_r], fill=edge, width=ss)
    return img.resize((tw, th), Image.LANCZOS)


# --------------------------------------------------------------------------
# Characters
# --------------------------------------------------------------------------


def _dir_flags(direction: str) -> tuple[int, bool]:
    """(fx, back) - fx=+1 faces right, -1 faces left; back=True shows the back of the head."""
    return (1 if direction in ("se", "ne") else -1), direction in ("ne", "nw")


def draw_character(spec: dict[str, Any], look: dict[str, str], pose: str,
                   direction: str = "se", walk_phase: int | None = None) -> Image.Image:
    """One 64x96 frame. ``walk_phase`` 0..3 (stand, step A, stand, step B) overrides the pose with a walk cycle."""
    cfg = spec["character"]
    ss = int(spec["supersample"])
    fw, fh = cfg["frameWidth"], cfg["frameHeight"]
    img = Image.new("RGBA", (fw * ss, fh * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    skin, hair = rgb(look["skin"]), rgb(look["hair"])
    outfit, accent = rgb(look["outfit"]), rgb(look["accent"])
    pants = shade(outfit, 0.5)
    shoe = (34, 36, 46)
    fx, back = _dir_flags(direction)

    if walk_phase is not None:
        step = {1: 5, 3: -5}.get(walk_phase, 0)
        bob = 1.5 if walk_phase in (1, 3) else 0.0
        pose = "walk"
    else:
        step = {"walk_a": 5, "walk_b": -5}.get(pose, 0)
        bob = 0.0
    seated = pose in ("working_seated", "meeting_seated", "resting")
    cx = fw / 2
    foot_y = fh * cfg["anchor"][1]

    def px(v: float) -> float:
        return v * ss

    def rrect(x0: float, y0: float, x1: float, y1: float, fill: RGB, r: float = 2.5) -> None:
        d.rounded_rectangle([px(x0), px(y0), px(x1), px(y1)], radius=px(r), fill=fill)

    def limb(x0: float, y0: float, x1: float, y1: float, fill: RGB, wd: float = 5) -> None:
        d.line([px(x0), px(y0), px(x1), px(y1)], fill=fill, width=int(wd * ss))
        r = wd / 2
        for x, y in ((x0, y0), (x1, y1)):
            d.ellipse([px(x - r), px(y - r), px(x + r), px(y + r)], fill=fill)

    # ground shadow (skipped for seated poses; the chair casts its own)
    if not seated:
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).ellipse([px(cx - 14), px(foot_y - 4), px(cx + 14), px(foot_y + 4)], fill=(0, 0, 0, 70))
        img = Image.alpha_composite(img, layer)
        d = ImageDraw.Draw(img)

    drop = 15 if seated else 0
    lift = 5 if pose == "celebration" else 0
    hip_y = foot_y - 25 + drop - lift - bob
    torso_top = hip_y - 24
    head_cy = torso_top - 11
    leg_dx = 1.5 * fx  # slight body turn so left/right facing read differently

    # legs
    if seated:
        for sx in (-5, 5):
            limb(cx + sx + leg_dx, hip_y, cx + sx + 3 * fx, hip_y + 5, pants, 7)
            limb(cx + sx + 3 * fx, hip_y + 5, cx + sx + 5 * fx, hip_y + 19, pants, 6)
            rrect(cx + sx + 2 * fx, hip_y + 18, cx + sx + 9 * fx if fx > 0 else cx + sx - 2, hip_y + 22, shoe, 1.5)
    else:
        for side in (-1, 1):
            off = step * side * (1 if fx > 0 else -1)
            limb(cx + side * 4, hip_y, cx + side * 4 + off, foot_y - 3 - (abs(step) * 0.3 if off > 0 else 0), pants, 6)
            rrect(cx + side * 4 + off - 4, foot_y - 4, cx + side * 4 + off + 4, foot_y + 1, shoe, 1.5)
    # arms behind torso when facing away
    sh_y = torso_top + 5
    swing = -step * 0.9
    def arm(side: int, ex: float, ey: float) -> None:
        limb(cx + side * 9, sh_y, cx + side * 9 + ex, sh_y + ey, outfit, 4.5)
        d.ellipse([px(cx + side * 9 + ex - 2.4), px(sh_y + ey - 2.4), px(cx + side * 9 + ex + 2.4), px(sh_y + ey + 2.4)], fill=skin)
    if pose == "celebration":
        arm(-1, -8, -17); arm(1, 8, -17)
    elif pose == "emergency":
        arm(-1, -11, 3); arm(1, 11, 3)
    elif pose == "working_seated":
        arm(-1, 2, 13); arm(1, -2, 13)
    elif pose == "meeting_seated":
        arm(-1, -3, 12); arm(1, 6, -9)
    elif pose == "resting":
        arm(-1, -6, -5); arm(1, 6, -5)
    else:
        arm(-1, -2 + 0, 15 + swing); arm(1, 2, 15 - swing)
    # torso (two-tone for volume) + collar/belt
    rrect(cx - 10, torso_top, cx + 10, hip_y + 2, outfit, 4)
    d.rounded_rectangle([px(cx + (0 if fx > 0 else -10)), px(torso_top + 2), px(cx + (10 if fx > 0 else 0)), px(hip_y + 2)],
                        radius=px(3), fill=shade(outfit, 0.82))
    rrect(cx - 10, hip_y - 4, cx + 10, hip_y, accent, 1.5)
    if not back:
        d.polygon([(px(cx - 4), px(torso_top)), (px(cx + 4), px(torso_top)), (px(cx), px(torso_top + 6))], fill=mix(skin, (255, 255, 255), 0.1))
    # head
    tilt = -2 * fx if pose == "resting" else 0
    hx = cx + tilt + 1.2 * fx
    d.ellipse([px(hx - 9.5), px(head_cy - 10), px(hx + 9.5), px(head_cy + 9)], fill=skin)
    style = look["style"]
    if back:
        d.ellipse([px(hx - 10), px(head_cy - 11), px(hx + 10), px(head_cy + 8)], fill=hair)
    else:
        d.pieslice([px(hx - 10.5), px(head_cy - 12), px(hx + 10.5), px(head_cy + 8)], 180, 360, fill=hair)
        d.rectangle([px(hx - 10), px(head_cy - 4), px(hx - 8), px(head_cy - 1)], fill=hair)
        d.rectangle([px(hx + 8), px(head_cy - 4), px(hx + 10), px(head_cy - 1)], fill=hair)
    if style == "long":
        rrect(hx - 11, head_cy - 5, hx - 6, head_cy + 13, hair, 2.5)
        rrect(hx + 6, head_cy - 5, hx + 11, head_cy + 13, hair, 2.5)
    elif style == "bun":
        d.ellipse([px(hx - 4.5), px(head_cy - 19), px(hx + 4.5), px(head_cy - 10)], fill=hair)
    elif style == "cap":
        d.pieslice([px(hx - 10.5), px(head_cy - 13), px(hx + 10.5), px(head_cy + 5)], 180, 360, fill=accent)
        rrect(hx + (-2 if fx > 0 else -12), head_cy - 5, hx + (12 if fx > 0 else 2), head_cy - 2.5, accent, 1.2)
    if not back:
        ex = 2.2 * fx
        for sx in (-4, 4):
            d.ellipse([px(hx + sx + ex - 1.8), px(head_cy - 1.5), px(hx + sx + ex + 1.8), px(head_cy + 2.2)], fill=(25, 25, 32))
            d.ellipse([px(hx + sx + ex - 0.2), px(head_cy - 1.2), px(hx + sx + ex + 0.9), px(head_cy - 0.1)], fill=(255, 255, 255))
        d.arc([px(hx - 2 + ex), px(head_cy + 3), px(hx + 2 + ex), px(head_cy + 6.5)], 20, 160, fill=shade(skin, 0.6), width=max(1, ss // 2))
    if pose == "emergency":  # red "!" so the state reads even when tiny
        rrect(cx - 1.8, head_cy - 31, cx + 1.8, head_cy - 20, (239, 68, 68), 1.5)
        d.ellipse([px(cx - 2.2), px(head_cy - 18), px(cx + 2.2), px(head_cy - 13.6)], fill=(239, 68, 68))
    # outline: dilate alpha, paint under the sprite
    alpha = img.split()[3].point(lambda v: 255 if v > 40 else 0)
    ring = alpha.filter(ImageFilter.MaxFilter(2 * ss + 1))
    under = Image.new("RGBA", img.size, OUTLINE + (255,))
    under.putalpha(ring)
    out = Image.alpha_composite(under, img)
    return out.resize((fw, fh), Image.LANCZOS)


def draw_character_sheet(spec: dict[str, Any], look: dict[str, str]) -> Image.Image:
    cfg = spec["character"]
    poses = cfg["poses"]
    sheet = Image.new("RGBA", (cfg["frameWidth"] * len(poses), cfg["frameHeight"]), (0, 0, 0, 0))
    for i, pose in enumerate(poses):
        sheet.paste(draw_character(spec, look, pose), (i * cfg["frameWidth"], 0))
    return sheet


def draw_walk_sheet(spec: dict[str, Any], look: dict[str, str]) -> Image.Image:
    """4 directions (rows, ``WALK_DIRECTIONS``) x 4 frames (cols): stand, step A, stand, step B."""
    cfg = spec["character"]
    fw, fh = cfg["frameWidth"], cfg["frameHeight"]
    sheet = Image.new("RGBA", (fw * WALK_FRAMES, fh * len(WALK_DIRECTIONS)), (0, 0, 0, 0))
    for r, direction in enumerate(WALK_DIRECTIONS):
        for f in range(WALK_FRAMES):
            sheet.paste(draw_character(spec, look, "walk_a", direction, walk_phase=f), (f * fw, r * fh))
    return sheet
