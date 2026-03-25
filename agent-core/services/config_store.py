from pathlib import Path

import yaml

from services.cosmos import CosmosAppConfigStore, CosmosClientFactory


class ConfigurationStore:
    def __init__(self, config_dir: str, cosmos_config: dict | None = None) -> None:
        self.config_dir = Path(config_dir)
        self.cosmos_store = CosmosAppConfigStore(CosmosClientFactory(cosmos_config))

    def list_applications(self) -> list[dict]:
        applications: list[dict] = []
        for path in sorted(self.config_dir.glob("app-*.yaml")):
            with path.open("r", encoding="utf-8") as handle:
                payload = yaml.safe_load(handle) or {}
            applications.append(
                {
                    "application_id": payload.get("application_id", path.stem),
                    "display_name": payload.get("display_name", path.stem),
                    "source": "file",
                }
            )
        return applications

    def load_application(self, application_id: str) -> dict:
        if self.cosmos_store.enabled:
            try:
                return self.cosmos_store.load_application(application_id)
            except FileNotFoundError:
                pass

        path = self.config_dir / f"{application_id}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Application configuration not found: {application_id}")

        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
