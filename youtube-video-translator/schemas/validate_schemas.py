#!/usr/bin/env python3
"""
Validate all JSON schema files in this directory against JSON Schema Draft7.
Run without arguments from the schemas/ directory.
"""
import json
import sys
from pathlib import Path

try:
    import jsonschema
except ImportError:
    print("jsonschema is required. Install: pip install jsonschema")
    sys.exit(1)


def main():
    schema_dir = Path(__file__).parent
    schemas = sorted(schema_dir.glob("*.schema.json"))

    if not schemas:
        print("No .schema.json files found.")
        sys.exit(1)

    all_valid = True
    for f in schemas:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            jsonschema.Draft7Validator.check_schema(data)
            print(f"  OK: {f.name}")
        except Exception as e:
            print(f"  FAIL: {f.name}: {e}")
            all_valid = False

    if all_valid:
        print(f"\nAll {len(schemas)} schemas are valid JSON Schema Draft7.")
        sys.exit(0)
    else:
        print("\nSome schemas have errors.")
        sys.exit(1)


if __name__ == "__main__":
    main()
