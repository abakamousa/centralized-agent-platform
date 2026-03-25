# Centralized Agent Platform


## Overview

The platform is organized into five main domains:
<img width="1681" height="971" alt="architecture drawio(1)" src="https://github.com/user-attachments/assets/0cc47edb-7041-4ebc-bfb2-0126707e1ac1" />


- `infrastructure/`: Terraform modules and environment definitions for Azure Container Apps, Cosmos DB, identities, networking, and observability.
- `agent-core/`: The Python runtime that authenticates requests, loads app definitions, executes workflow graphs, manages session memory, and calls the hosted LLM.
- `mcp-servers/`: Independently deployable MCP tool servers for cloud and data integrations.
- `app/`: Application-specific YAML definitions that describe workflow topology, prompts, and allowed tools.
- `configurations/`: Shared schemas and validation utilities for the app definitions.

## Architecture

The request path is:

1. A client application calls `agent-core` with an Auth0 bearer token.
2. Auth0 may federate the user through Microsoft Entra ID.
3. `agent-core` validates the Auth0 token and derives a `user_id` and `session_id`.
4. The runtime loads the target app definition from `app/*.yaml`.
5. The workflow is executed dynamically from `workflow.entrypoint`.
6. Tool nodes call the allowed MCP servers with forwarded user context.
7. LLM nodes call Azure AI Foundry by using the agent runtime's Microsoft Entra identity.
8. Guardrails validate user input for prompt injection and optionally redact PII before workflow execution.
9. LangGraph memory stores thread state for the session, optionally in Cosmos DB.
10. MLflow captures execution traces and metrics.

## Repository Layout

```text
/centralized-agent-platform
|-- .github/workflows/
|-- infrastructure/
|-- agent-core/
|-- mcp-servers/
|-- app/
|-- configurations/
`-- docker-compose.yml
```

## Agent Core

`agent-core` is configuration-driven. It does not hardcode a specific app workflow. Instead, it:

- loads the selected app definition at runtime
- builds execution behavior from the declared workflow nodes
- supports `classifier`, `tool`, and `llm` nodes today
- keeps LangGraph-backed in-memory thread state
- separates end-user authentication from Azure model authentication

The main request model currently supports:

- `application_id`
- `input`
- `session_id` optional
- `thread_id` optional
- `context` optional

## Identity And Sessions

The identity model is intentionally split:

- End-user access to `agent-core` is protected by Auth0.
- Auth0 can federate enterprise identities from Microsoft Entra ID.
- `agent-core` validates Auth0 bearer tokens with issuer and audience checks.
- Each request is associated with a `user_id` and `session_id`.
- The LLM call to Azure AI Foundry uses the agent runtime's Azure identity, not the Auth0 user token.

Session handling works like this:

- send `session_id` in the request body, or
- send `X-Session-Id` as a header, or
- let the runtime fall back to the Auth0 token session claim such as `sid`

If no explicit `thread_id` is provided, the runtime derives one as:

```text
application_id:user_id:session_id
```

That default keeps multiple user sessions separated even for the same application.

## Guardrails

The runtime supports optional request guardrails before any workflow node executes.

- Prompt injection detection can be enabled or disabled per runtime profile.
- Prompt injection can currently block the request when suspicious patterns are detected.
- PII redaction can be enabled or disabled per runtime profile.
- When PII redaction is enabled, common patterns such as emails, phone numbers, SSNs, and card-like values are masked before the workflow runs.

Guardrail settings live in [runtime.yaml](/c:/Users/abaka/Documents/sdk_ai_agent/centralized-agent-platform/agent-core/config/runtime.yaml) under each profile.

## LangGraph Memory

The runtime uses LangGraph memory with two modes:

- Cosmos-backed persistent checkpoints when the selected runtime profile enables Cosmos memory.
- In-memory checkpointing as a fallback when Cosmos persistence is disabled.

Reuse the same `thread_id` to continue the same conversation thread. Reuse the same `session_id` to keep requests associated to the same authenticated session.

## App Definitions

Application behavior lives in `app/*.yaml`.

Each app definition can declare:

- app metadata such as `application_id` and `display_name`
- a `system_prompt`
- an `authorization` policy for allowed MCP servers
- a `workflow.entrypoint`
- workflow `nodes`
- tool permissions and server bindings

Supported workflow node fields currently include:

- `type`: `classifier`, `tool`, or `llm`
- `next`: next node id
- `tool`: tool name for tool nodes
- `prompt`: response prompt for llm nodes
- `routes`: optional keyword routing for classifier nodes

MCP authorization is enforced in two layers:

- the app must explicitly list the MCP servers it is allowed to use in `authorization.allowed_mcp_servers`
- the caller must have the permissions declared on each tool, typically from Auth0 `permissions` or `scope` claims

Example apps already included:

- `app-customer-support`
- `app-cloudops-bot`
- `app-internal-hr`
- `app-sales-analytics`

## Runtime Profiles

Runtime connectivity and credentials are selected from [runtime.yaml](/c:/Users/abaka/Documents/sdk_ai_agent/centralized-agent-platform/agent-core/config/runtime.yaml).

The file currently supports:

- `dev`
- `prod`

Each profile can define:

- Auth0 issuer and audience
- Cosmos DB endpoint, database, containers, and enablement flag
- Azure AI Foundry endpoint, deployment, and API version

Shared sections also define:

- MLflow tracking URI
- MCP server base URLs

The active profile is selected with `AGENT_ENV`.

When Cosmos is enabled in the selected profile:

- app definitions are loaded from Cosmos DB first
- local `app/*.yaml` files remain as a fallback for missing apps
- LangGraph checkpoints are stored in the configured Cosmos memory container

The sample runtime profiles keep Cosmos disabled by default until real resources and credentials are configured.

## Local Development

Python services use `uv` for dependency management.

Run the core service locally:

```bash
cd agent-core
uv sync
uv run uvicorn main:app --reload
```

Run the Angular test console:

```bash
cd angular-test-ui
npm install
npm start
```

Validate app definitions:

```bash
uv run --with jsonschema --with pyyaml python configurations/validate_configs.py
```

Run the local stack with Docker Compose:

```bash
docker compose up --build
```

Run with the development profile:

```powershell
$env:AGENT_ENV="dev"
docker compose up --build
```

Run with the production profile values:

```powershell
$env:AGENT_ENV="prod"
docker compose up --build
```

The compose stack mounts:

- `./app` into the runtime for app definitions
- `./agent-core/config` into the runtime for environment profiles

The Angular UI runs on `http://localhost:4200` and proxies API calls to `agent-core` on `http://localhost:8000`.

## Example Request

```json
{
  "application_id": "app-internal-hr",
  "session_id": "session-123",
  "thread_id": "app-internal-hr:user-42:session-123",
  "input": "What is our parental leave policy?"
}
```

You can also omit `thread_id` and let the runtime derive it from the app, user, and session.

## Web Test UI

An Angular-based test console is available in [angular-test-ui](c:/Users/abaka/Documents/sdk_ai_agent/centralized-agent-platform/angular-test-ui).

It supports:

- selecting a saved app config from the backend
- loading and inspecting the current app YAML
- sending requests through simple form fields
- pasting a YAML config and invoking it through preview mode
- testing bearer token, session, and thread values without editing backend files

## CI/CD

This monorepo is designed for path-based automation:

- changes in `infrastructure/` trigger Terraform plan or apply
- changes in `agent-core/` rebuild and deploy the runtime
- changes in a specific `mcp-servers/<tool>/` folder deploy only that tool
- changes in `app/` and `configurations/` validate schemas and sync app definitions to Cosmos DB


