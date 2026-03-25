import json
from pathlib import Path

from jsonschema import validate


ROOT = Path(__file__).parent
SCHEMA_PATH = ROOT / "schemas" / "application.schema.json"


def main() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    config_files = sorted(ROOT.glob("app-*.json"))

    for path in config_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate(instance=payload, schema=schema)
        print(f"validated {path.name}")


if __name__ == "__main__":
    main()
