from pathlib import Path

import yaml


class ConfigurationStore:
    def __init__(self, config_dir: str) -> None:
        self.config_dir = Path(config_dir)

    def load_application(self, application_id: str) -> dict:
        path = self.config_dir / f"{application_id}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Application configuration not found: {application_id}")

        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
