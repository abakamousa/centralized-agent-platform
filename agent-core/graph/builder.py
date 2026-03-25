import operator
from collections.abc import Callable
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from services.cosmos import CosmosCheckpointSaver, CosmosClientFactory
from services.mcp_client import MCPClientRegistry
from services.foundry_client import FoundryModelClient


class WorkflowExecutionError(RuntimeError):
    pass


class MCPAuthorizationError(WorkflowExecutionError):
    pass


class AgentGraphState(TypedDict, total=False):
    application_id: str
    input: str
    session_id: str
    context: dict[str, Any]
    system_prompt: str | None
    identity: dict[str, str]
    app_config: dict[str, Any]
    messages: Annotated[list[dict[str, str]], operator.add]
    execution_history: Annotated[list[dict[str, Any]], operator.add]
    last_result: dict[str, Any]


class DynamicGraphRunner:
    def __init__(
        self,
        observability,
        foundry_config: dict[str, Any],
        mcp_config: dict[str, Any],
        cosmos_config: dict[str, Any],
    ) -> None:
        self.observability = observability
        self.mcp_registry = MCPClientRegistry(mcp_config=mcp_config)
        self.foundry_client = FoundryModelClient(foundry_config=foundry_config)
        cosmos_checkpointer = CosmosCheckpointSaver(CosmosClientFactory(cosmos_config))
        self.checkpointer = cosmos_checkpointer if cosmos_checkpointer.enabled else InMemorySaver()
        self.node_handlers: dict[str, Callable[..., Any]] = {
            "classifier": self._run_classifier_node,
            "llm": self._run_llm_node,
            "tool": self._run_tool_node,
        }
        self.graph = self._build_graph()

    async def run(self, request, identity, app_config: dict[str, Any]) -> dict[str, Any]:
        thread_id = (
            request.thread_id
            or f"{request.application_id}:{identity.user_id}:{identity.session_id}"
        )
        initial_state: AgentGraphState = {
            "application_id": request.application_id,
            "input": request.input,
            "session_id": identity.session_id,
            "context": request.context or {},
            "system_prompt": app_config.get("system_prompt"),
            "identity": {
                "authorization": identity.authorization,
                "user_id": identity.user_id,
                "session_id": identity.session_id,
                "permissions": identity.permissions,
            },
            "app_config": app_config,
            "messages": [{"role": "user", "content": request.input}],
        }

        graph_state = await self.graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": thread_id}},
        )
        result = dict(graph_state["last_result"])
        result["thread_id"] = thread_id
        result["session"] = {
            "session_id": identity.session_id,
            "user_id": identity.user_id,
        }
        result["memory"] = {
            "message_count": len(graph_state.get("messages", [])),
            "turn_count": len(graph_state.get("execution_history", [])),
        }
        return result

    def _build_graph(self):
        builder = StateGraph(AgentGraphState)
        builder.add_node("execute_workflow", self._execute_workflow)
        builder.add_edge(START, "execute_workflow")
        builder.add_edge("execute_workflow", END)
        return builder.compile(checkpointer=self.checkpointer)

    async def _execute_workflow(self, state: AgentGraphState) -> AgentGraphState:
        identity = state["identity"]
        app_config = state["app_config"]
        workflow = app_config.get("workflow", {})
        authorization_policy = app_config.get("authorization", {})
        nodes = workflow.get("nodes", [])
        entrypoint = workflow.get("entrypoint")
        node_map = {node["id"]: node for node in nodes}
        tools_by_name = {tool["name"]: tool for tool in app_config.get("tools", [])}
        allowed_mcp_servers = set(authorization_policy.get("allowed_mcp_servers", []))
        execution_trace: list[dict[str, Any]] = []
        visited_nodes: set[str] = set()

        if not entrypoint:
            raise WorkflowExecutionError("Workflow entrypoint is missing")

        if entrypoint not in node_map:
            raise WorkflowExecutionError(f"Workflow entrypoint '{entrypoint}' is not defined")

        self.observability.start_trace(state["application_id"], identity["user_id"])

        current_node_id: str | None = entrypoint
        workflow_state: dict[str, Any] = {
            "application_id": state["application_id"],
            "input": state["input"],
            "session_id": state["session_id"],
            "context": state.get("context", {}),
            "system_prompt": app_config.get("system_prompt"),
            "node_outputs": {},
            "messages": state.get("messages", []),
        }

        while current_node_id is not None:
            if current_node_id in visited_nodes:
                raise WorkflowExecutionError(
                    f"Detected workflow cycle at node '{current_node_id}'"
                )

            visited_nodes.add(current_node_id)
            node = node_map.get(current_node_id)
            if node is None:
                raise WorkflowExecutionError(f"Workflow node '{current_node_id}' is not defined")

            handler = self.node_handlers.get(node["type"])
            if handler is None:
                raise WorkflowExecutionError(
                    f"Unsupported workflow node type '{node['type']}' for node '{current_node_id}'"
                )

            node_result = await handler(
                node=node,
                state=workflow_state,
                identity=identity,
                tools_by_name=tools_by_name,
                allowed_mcp_servers=allowed_mcp_servers,
            )
            workflow_state["node_outputs"][current_node_id] = node_result
            execution_trace.append(
                {
                    "node_id": current_node_id,
                    "node_type": node["type"],
                    "result": node_result,
                }
            )
            current_node_id = self._resolve_next_node(node=node, node_result=node_result)

        result = {
            "application_id": state["application_id"],
            "workflow": workflow,
            "response": self._build_response(state=workflow_state, execution_trace=execution_trace),
            "execution_trace": execution_trace,
        }

        self.observability.log_result(result)
        return {
            "messages": [{"role": "assistant", "content": result["response"]}],
            "execution_history": [
                {
                    "application_id": state["application_id"],
                    "session_id": state["session_id"],
                    "input": state["input"],
                    "response": result["response"],
                }
            ],
            "last_result": result,
        }

    def _resolve_next_node(self, node: dict[str, Any], node_result: dict[str, Any]) -> str | None:
        next_node = node_result.get("next")
        if next_node is not None:
            return next_node
        return node.get("next")

    def _build_response(
        self, state: dict[str, Any], execution_trace: list[dict[str, Any]]
    ) -> str:
        for step in reversed(execution_trace):
            result = step["result"]
            if isinstance(result, dict) and "response" in result:
                return str(result["response"])

        return f"Processed request for {state['application_id']}"

    async def _run_classifier_node(
        self,
        *,
        node: dict[str, Any],
        state: dict[str, Any],
        identity,
        tools_by_name: dict[str, dict[str, Any]],
        allowed_mcp_servers: set[str],
    ) -> dict[str, Any]:
        del identity, tools_by_name, allowed_mcp_servers
        routes = node.get("routes", [])
        default_next = node.get("next")
        selected_next = default_next

        if routes:
            lowered_input = state["input"].lower()
            for route in routes:
                keywords = [keyword.lower() for keyword in route.get("keywords", [])]
                if keywords and any(keyword in lowered_input for keyword in keywords):
                    selected_next = route.get("next", default_next)
                    break

        return {
            "classification": node.get("label", "classified"),
            "next": selected_next,
        }

    async def _run_tool_node(
        self,
        *,
        node: dict[str, Any],
        state: dict[str, Any],
        identity,
        tools_by_name: dict[str, dict[str, Any]],
        allowed_mcp_servers: set[str],
    ) -> dict[str, Any]:
        tool_name = node.get("tool")
        if not tool_name:
            raise WorkflowExecutionError(f"Tool node '{node['id']}' is missing a tool reference")

        tool = tools_by_name.get(tool_name)
        if tool is None:
            raise WorkflowExecutionError(
                f"Tool '{tool_name}' referenced by node '{node['id']}' is not defined"
            )

        tool_server = tool["server"]
        if allowed_mcp_servers and tool_server not in allowed_mcp_servers:
            raise MCPAuthorizationError(
                f"App is not authorized to use MCP server '{tool_server}'"
            )

        required_permissions = [str(item) for item in tool.get("permissions", [])]
        granted_permissions = set(identity.get("permissions", []))
        missing_permissions = [
            permission
            for permission in required_permissions
            if permission not in granted_permissions
        ]
        if missing_permissions:
            raise MCPAuthorizationError(
                "Caller is not authorized for tool "
                f"'{tool_name}'. Missing permissions: {', '.join(missing_permissions)}"
            )

        client = self.mcp_registry.get(tool_server)
        if client is None:
            return {
                "tool": tool["name"],
                "status": "skipped",
                "reason": "server_not_configured",
            }

        tool_input = node.get("input", state["input"])
        return await client.invoke(
            tool_name=tool["name"],
            query=tool_input,
            authorization=identity["authorization"],
            user_id=identity["user_id"],
        )

    async def _run_llm_node(
        self,
        *,
        node: dict[str, Any],
        state: dict[str, Any],
        identity,
        tools_by_name: dict[str, dict[str, Any]],
        allowed_mcp_servers: set[str],
    ) -> dict[str, Any]:
        del identity, tools_by_name, allowed_mcp_servers
        prompt = node.get("prompt") or state.get("system_prompt") or "Respond to the request."
        prior_messages = state.get("messages", [])[:-1]
        tool_summaries = [
            output
            for output in state["node_outputs"].values()
            if isinstance(output, dict) and output.get("status") == "success"
        ]
        response = (
            f"{prompt} Input: {state['input']}. "
            f"Collected {len(tool_summaries)} successful tool result(s). "
            f"Memory contains {len(prior_messages)} prior message(s)."
        )

        messages = [
            {"role": "system", "content": prompt},
            *prior_messages,
            {"role": "user", "content": state["input"]},
        ]
        if tool_summaries:
            messages.append(
                {
                    "role": "system",
                    "content": f"Tool results: {tool_summaries}",
                }
            )

        if not self.foundry_client.enabled:
            return {"response": response, "provider": "stub"}

        completion = await self.foundry_client.chat(messages=messages)
        content = (
            completion.get("choices", [{}])[0]
            .get("message", {})
            .get("content", response)
        )
        return {"response": content, "provider": "azure-ai-foundry"}
