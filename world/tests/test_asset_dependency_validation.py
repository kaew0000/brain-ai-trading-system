"""Phase W6: dependency integrity and duplicate-id detection.

These wrap `world/scripts/validate_assets.py` (the single implementation of
these checks, also runnable standalone / in CI) rather than re-implementing
the logic here."""
import os
import sys

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(WORLD_ROOT, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from validate_assets import validate_all  # noqa: E402


def test_no_validation_errors_at_all():
    errors = validate_all()
    assert errors == [], f"Phase W6 validation errors: {errors}"


def test_manifest_dependencies_all_resolve():
    """Focused re-check: every dependency of every manifest entry exists.
    (Full coverage already lives in `validate_all`; this isolates the one
    failure mode so a broken dependency shows up as its own red test.)"""
    import json

    manifest_path = os.path.join(WORLD_ROOT, "data", "assets", "asset_manifest.json")
    with open(manifest_path) as f:
        manifest = json.load(f)
    ids = {e["id"] for e in manifest}
    for entry in manifest:
        for dep in entry.get("dependencies", []):
            assert dep in ids, f"{entry['id']} depends on missing {dep}"


def test_manifest_has_at_least_one_real_dependency_edge():
    """Guards against the dependency feature silently becoming dead code —
    at least one manifest entry must actually declare a dependency."""
    import json

    manifest_path = os.path.join(WORLD_ROOT, "data", "assets", "asset_manifest.json")
    with open(manifest_path) as f:
        manifest = json.load(f)
    assert any(entry.get("dependencies") for entry in manifest)
