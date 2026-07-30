"""Scene — one room's static renderable content. Deliberately mirrors
`world/scenes/scene-manifest.schema.json` (Phase W1) field-for-field
so the two never drift apart; extends it with `layers`, which W1's
design-only schema did not yet need."""

from dataclasses import dataclass, field

from world.frontend.scene.layer import Layer


@dataclass
class Scene:
    """One scene = one room. `district_id` must be a real id from
    `world/districts/definitions/`; `character_ids` must be a subset
    of the characters placed there per
    `world/data/characters/placement.json`."""

    scene_id: str
    district_id: str
    character_ids: list[str] = field(default_factory=list)
    layers: list[Layer] = field(default_factory=list)

    def to_manifest_dict(self) -> dict:
        """Return the subset of fields that match
        `world/scenes/scene-manifest.schema.json` — used by
        `world/tests/test_frontend_schemas.py` to keep this class and
        that schema from drifting apart."""
        return {
            "sceneId": self.scene_id,
            "districtId": self.district_id,
            "characterIds": list(self.character_ids),
        }


class SceneRegistry:
    """In-memory, engine-agnostic registry of `Scene` instances,
    keyed by `scene_id`. A concrete `Renderer` uses this to look up
    which `Scene` to hand to `SceneRenderer.enter`/`exit`; it does not
    render anything itself."""

    def __init__(self) -> None:
        self._scenes: dict[str, Scene] = {}

    def register(self, scene: Scene) -> None:
        self._scenes[scene.scene_id] = scene

    def get(self, scene_id: str) -> Scene | None:
        return self._scenes.get(scene_id)

    def all_scenes(self) -> list[Scene]:
        return list(self._scenes.values())
