"""Placeholder test: every schema/sample JSON file is valid and consistent."""
import os
import sys

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(WORLD_ROOT, "scripts"))

from validate_schemas import validate_all  # noqa: E402


def test_all_world_json_is_valid():
    errors = validate_all()
    assert errors == [], f"world/ JSON validation errors: {errors}"
