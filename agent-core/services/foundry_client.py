import os
from typing import Any

import httpx
from azure.identity import DefaultAzureCredential


class FoundryModelClient:
    def __init__(self, foundry_config: dict[str, Any] | None = None) -> None:
        config = foundry_config or {}
        self.base_url = str(
            config.get("endpoint") or os.getenv("FOUNDRY_OPENAI_BASE_URL", "")
        ).rstrip("/")
        self.model = str(config.get("deployment") or os.getenv("FOUNDRY_MODEL_DEPLOYMENT", ""))
        self.api_version = str(config.get("api_version") or os.getenv("FOUNDRY_API_VERSION", "2024-10-21"))
        self.credential = DefaultAzureCredential()

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.model)

    async def chat(self, messages: list[dict[str, str]], max_tokens: int = 400) -> dict[str, Any]:
        token = self.credential.get_token("https://ai.azure.com/.default").token
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                params={"api-version": self.api_version},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            return response.json()
