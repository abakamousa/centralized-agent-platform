import json
from pathlib import Path

from jsonschema import validate
import yaml


ROOT = Path(__file__).parent
SCHEMA_PATH = ROOT / "schemas" / "application.schema.json"
APP_ROOT = ROOT.parent / "app"


def main() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    config_files = sorted(APP_ROOT.glob("app-*.yaml"))

    for path in config_files:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        validate(instance=payload, schema=schema)
        print(f"validated {path.name}")


if __name__ == "__main__":
    main()
