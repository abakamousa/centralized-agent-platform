import os
from pathlib import Path
from typing import Any

import yaml


class RuntimeConfigError(RuntimeError):
    pass


class RuntimeConfig:
    def __init__(self, payload: dict[str, Any], environment: str) -> None:
        self.payload = payload
        self.environment = environment

    @classmethod
    def load(cls) -> "RuntimeConfig":
        config_path = Path(os.getenv("AGENT_RUNTIME_CONFIG", "/app/config/runtime.yaml"))
        environment = os.getenv("AGENT_ENV", "dev")

        if not config_path.exists():
            raise RuntimeConfigError(f"Runtime config file not found: {config_path}")

        with config_path.open("r", encoding="utf-8") as handle:
            raw_config = yaml.safe_load(handle) or {}

        profiles = raw_config.get("profiles", {})
        if environment not in profiles:
            raise RuntimeConfigError(
                f"Runtime config profile '{environment}' is not defined in {config_path}"
            )

        selected_profile = profiles[environment]
        payload = {
            "environment": environment,
            "auth0": selected_profile.get("auth0", {}),
            "cosmos": selected_profile.get("cosmos", {}),
            "foundry": selected_profile.get("foundry", {}),
            "guardrails": selected_profile.get("guardrails", raw_config.get("guardrails", {})),
            "observability": raw_config.get("observability", {}),
            "mcp": raw_config.get("mcp", {}),
        }
        return cls(payload=payload, environment=environment)

    def section(self, name: str) -> dict[str, Any]:
        value = self.payload.get(name, {})
        return value if isinstance(value, dict) else {}
