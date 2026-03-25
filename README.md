# Centralized Agent Platform

This repository contains the infrastructure, runtime engine, tool servers, and GitOps-managed app definitions for a centralized AI agent platform.

## Overview

The platform is organized into five main domains:

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
8. LangGraph memory stores thread state for the session.
9. MLflow captures execution traces and metrics.

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

## LangGraph Memory

The runtime uses LangGraph with an in-memory checkpointer.

- Reuse the same `thread_id` to continue the same conversation thread.
- Reuse the same `session_id` to keep requests associated to the same authenticated session.
- Current memory is in-process only and does not survive container restarts.

## App Definitions

Application behavior lives in `app/*.yaml`.

Each app definition can declare:

- app metadata such as `application_id` and `display_name`
- a `system_prompt`
- a `workflow.entrypoint`
- workflow `nodes`
- tool permissions and server bindings

Supported workflow node fields currently include:

- `type`: `classifier`, `tool`, or `llm`
- `next`: next node id
- `tool`: tool name for tool nodes
- `prompt`: response prompt for llm nodes
- `routes`: optional keyword routing for classifier nodes

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
- Azure AI Foundry endpoint, deployment, and API version

Shared sections also define:

- MLflow tracking URI
- MCP server base URLs

The active profile is selected with `AGENT_ENV`.

## Local Development

Python services use `uv` for dependency management.

Run the core service locally:

```bash
cd agent-core
uv sync
uv run uvicorn main:app --reload
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

## CI/CD

This monorepo is designed for path-based automation:

- changes in `infrastructure/` trigger Terraform plan or apply
- changes in `agent-core/` rebuild and deploy the runtime
- changes in a specific `mcp-servers/<tool>/` folder deploy only that tool
- changes in `app/` and `configurations/` validate schemas and sync app definitions to Cosmos DB

## Current State

This repository is a working scaffold for the platform architecture. It includes:

- a dynamic workflow runner
- Auth0 token validation
- Azure AI Foundry model access through Entra identity
- LangGraph thread memory
- session-aware request handling
- MCP tool server examples
- Terraform and GitHub Actions starter structure

The next likely production steps would be persistent memory, real Cosmos DB-backed config loading, richer workflow branching, and stronger authorization checks per app and tool.
