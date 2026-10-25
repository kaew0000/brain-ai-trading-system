"""Phase W-ISO-1 — isometric projection, config resolution, frame wiring.

Backward compatibility is the primary contract: with no opt-in, every
projected coordinate and the frame's viewport math must be identical to
the pre-W-ISO-1 orthographic output.
"""

import json

import pytest

from world.frontend.renderer import render_config
from world.frontend.renderer.render_config import load_renderer_config
from world.frontend.viewport.viewport import (
    PROJECTION_ISOMETRIC,
    PROJECTION_ORTHOGRAPHIC,
    ViewportState,
    screen_to_world,
    world_to_screen,
)


def _vp(**kw) -> ViewportState:
    return ViewportState(width=1280, height=720, scale=32.0, **kw)


def test_default_projection_is_orthographic_and_unchanged():
    vp = _vp()
    assert vp.projection == PROJECTION_ORTHOGRAPHIC
    # (3 - 1) * 32 + 640 ; (2 - 1) * 32 + 360 — the legacy formula
    assert world_to_screen(vp, 1.0, 1.0, 3.0, 2.0) == (704.0, 392.0)


def test_isometric_camera_point_maps_to_viewport_center():
    vp = _vp(projection=PROJECTION_ISOMETRIC)
    assert world_to_screen(vp, 5.0, 7.0, 5.0, 7.0) == (640.0, 360.0)


def test_isometric_axes_are_two_to_one_diamond():
    vp = _vp(projection=PROJECTION_ISOMETRIC)
    x_axis = world_to_screen(vp, 0.0, 0.0, 1.0, 0.0)  # +x: down-right
    y_axis = world_to_screen(vp, 0.0, 0.0, 0.0, 1.0)  # +y: down-left
    assert x_axis == (640.0 + 32.0, 360.0 + 16.0)
    assert y_axis == (640.0 - 32.0, 360.0 + 16.0)


@pytest.mark.parametrize("projection", [PROJECTION_ORTHOGRAPHIC, PROJECTION_ISOMETRIC])
def test_round_trip(projection):
    vp = _vp(projection=projection, origin_x=12.0, origin_y=-8.0)
    for wx, wy in [(0.0, 0.0), (4.5, -2.25), (-10.0, 33.0)]:
        sx, sy = world_to_screen(vp, 1.5, -0.5, wx, wy)
        rx, ry = screen_to_world(vp, 1.5, -0.5, sx, sy)
        assert (rx, ry) == pytest.approx((wx, wy))


def test_invalid_projection_and_ratio_rejected():
    with pytest.raises(ValueError):
        _vp(projection="fisheye")
    with pytest.raises(ValueError):
        _vp(projection=PROJECTION_ISOMETRIC, iso_tile_ratio=0.0)


def test_config_default_is_orthographic(monkeypatch):
    monkeypatch.delenv(render_config.PROJECTION_ENV_VAR, raising=False)
    assert load_renderer_config().projection == PROJECTION_ORTHOGRAPHIC


def test_config_file_and_env_precedence(monkeypatch, tmp_path):
    cfg = tmp_path / "r.json"
    cfg.write_text(json.dumps({"engine": "phaser", "viewport": {"width": 10, "height": 10},
                               "projection": "isometric", "isoTileRatio": 0.4}))
    monkeypatch.delenv(render_config.PROJECTION_ENV_VAR, raising=False)
    loaded = load_renderer_config(str(cfg))
    assert (loaded.projection, loaded.iso_tile_ratio) == (PROJECTION_ISOMETRIC, 0.4)

    monkeypatch.setenv(render_config.PROJECTION_ENV_VAR, "orthographic")
    assert load_renderer_config(str(cfg)).projection == PROJECTION_ORTHOGRAPHIC  # env wins

    monkeypatch.setenv(render_config.PROJECTION_ENV_VAR, "bogus")
    assert load_renderer_config(str(cfg)).projection == render_config.DEFAULT_PROJECTION  # typo -> default


def test_frame_viewport_reports_projection(monkeypatch):
    from world.frontend.renderer.renderer import SceneGraphRenderer
    from world.frontend.renderer.world_state_provider import RenderWorldStateProvider

    monkeypatch.setenv(render_config.PROJECTION_ENV_VAR, "isometric")
    r = SceneGraphRenderer()
    r.initialize()
    r.render(RenderWorldStateProvider().get_current_state())
    frame = r.current_frame
    assert frame.viewport["projection"] == PROJECTION_ISOMETRIC
    assert frame.viewport["isoTileRatio"] == 0.5
    r.shutdown()
