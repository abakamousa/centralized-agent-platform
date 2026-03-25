from typing import Any

from services.mcp_client import MCPClientRegistry


class DynamicGraphRunner:
    def __init__(self, observability) -> None:
        self.observability = observability
        self.mcp_registry = MCPClientRegistry()

    async def run(self, request, identity, app_config: dict[str, Any]) -> dict[str, Any]:
        tools = app_config.get("tools", [])
        workflow = app_config.get("workflow", {})
        tool_results = []

        self.observability.start_trace(request.application_id, identity.user_id)

        for tool in tools:
            client = self.mcp_registry.get(tool["server"])
            if client is None:
                tool_results.append(
                    {
                        "tool": tool["server"],
                        "status": "skipped",
                        "reason": "server_not_configured",
                    }
                )
                continue

            tool_results.append(
                await client.invoke(
                    tool_name=tool["name"],
                    query=request.input,
                    authorization=identity.authorization,
                    user_id=identity.user_id,
                )
            )

        result = {
            "application_id": request.application_id,
            "workflow": workflow,
            "response": f"Processed request for {request.application_id}",
            "tool_results": tool_results,
        }

        self.observability.log_result(result)
        return result
