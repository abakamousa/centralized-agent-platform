import os
from typing import Any

import httpx


class MCPClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    async def invoke(
        self,
        tool_name: str,
        query: str,
        authorization: str,
        user_id: str,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{self.base_url}/invoke",
                json={"tool": tool_name, "query": query},
                headers={
                    "Authorization": authorization,
                    "X-User-Id": user_id,
                },
            )
            response.raise_for_status()
            payload = response.json()
            payload["server"] = self.base_url
            return payload


class MCPClientRegistry:
    def __init__(self) -> None:
        self.clients = {
            "mcp-aws-s3": self._client_from_env("MCP_AWS_S3_URL"),
            "mcp-azure-sql": self._client_from_env("MCP_AZURE_SQL_URL"),
        }

    def _client_from_env(self, env_name: str) -> MCPClient | None:
        base_url = os.getenv(env_name)
        return MCPClient(base_url) if base_url else None

    def get(self, name: str) -> MCPClient | None:
        return self.clients.get(name)
