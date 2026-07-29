"""
Placeholder validation script for world/ JSON contracts.

Validates:
- every *.schema.json file in world/data/schemas is valid JSON Schema
- every *.sample.json file in world/data/samples validates against its
  corresponding schema
- every character/district definition file is valid JSON

This script never touches anything outside world/.
"""
import json
import os
import sys

try:
    import jsonschema
except ImportError:
    jsonschema = None

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMAS_DIR = os.path.join(WORLD_ROOT, "data", "schemas")
SAMPLES_DIR = os.path.join(WORLD_ROOT, "data", "samples")


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def validate_all():
    errors = []

    # 1. schema files are valid JSON
    schema_map = {}
    for fname in sorted(os.listdir(SCHEMAS_DIR)):
        if not fname.endswith(".schema.json"):
            continue
        path = os.path.join(SCHEMAS_DIR, fname)
        try:
            schema_map[fname] = load_json(path)
        except Exception as e:
            errors.append(f"Invalid JSON in schema {fname}: {e}")

    # 2. sample files validate against matching schema
    for fname in sorted(os.listdir(SAMPLES_DIR)):
        if not fname.endswith(".sample.json"):
            continue
        base = fname.replace(".sample.json", "")
        schema_name = f"{base}.schema.json"
        sample_path = os.path.join(SAMPLES_DIR, fname)
        try:
            sample = load_json(sample_path)
        except Exception as e:
            errors.append(f"Invalid JSON in sample {fname}: {e}")
            continue
        schema = schema_map.get(schema_name)
        if schema is None:
            errors.append(f"No matching schema for sample {fname}")
            continue
        if jsonschema is not None:
            try:
                jsonschema.validate(instance=sample, schema=schema)
            except jsonschema.ValidationError as e:
                errors.append(f"{fname} failed validation against {schema_name}: {e.message}")

    # 3. character/district definitions are valid JSON
    for sub in ("characters/definitions", "districts/definitions"):
        d = os.path.join(WORLD_ROOT, sub)
        for fname in sorted(os.listdir(d)):
            if not fname.endswith(".json"):
                continue
            try:
                load_json(os.path.join(d, fname))
            except Exception as e:
                errors.append(f"Invalid JSON in {sub}/{fname}: {e}")

    return errors


if __name__ == "__main__":
    errs = validate_all()
    if errs:
        print("VALIDATION FAILED:")
        for e in errs:
            print(f"  - {e}")
        sys.exit(1)
    print("All world/ JSON schemas and samples validated successfully.")
