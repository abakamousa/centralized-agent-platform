# Centralized Agent Platform

This repository contains the infrastructure, runtime engine, tool servers, and runtime configurations for a centralized AI agent platform.

## Architecture Overview

The platform is split into four primary domains:

- `infrastructure/`: Terraform modules and environment definitions for Azure Container Apps, Cosmos DB, identities, networking, and observability.
- `agent-core/`: A generic Python runtime that loads application configuration at runtime, builds a LangGraph workflow dynamically, forwards user identity context, and emits telemetry.
- `mcp-servers/`: Independent Model Context Protocol tool servers for cloud and data integrations.
- `configurations/`: GitOps-managed application definitions, prompts, graph layout, and MCP permissions.

## Request Flow

1. A client application sends a request with user identity context.
2. The agent resolves the application configuration from Cosmos DB.
3. The agent builds the workflow dynamically from configuration.
4. The agent forwards user context to approved MCP servers.
5. The MCP layer accesses downstream systems using least-privilege boundaries.
6. MLflow captures execution traces and performance metrics.

## Repository Layout

```text
/centralized-agent-platform
├── .github/workflows/
├── infrastructure/
├── agent-core/
├── mcp-servers/
├── configurations/
└── docker-compose.yml
```

## Local Development

Python services in this repository use `uv` for dependency management.

Run the core service locally:

```bash
cd agent-core
uv sync
uv run uvicorn main:app --reload
```

Validate application configurations:

```bash
uv run --with jsonschema python configurations/validate_configs.py
```

Use Docker Compose to run the platform locally:

```bash
docker compose up --build
```

This starts:

- the `agent-core` API
- example `mcp-aws-s3` and `mcp-azure-sql` tool servers
- configuration mounting from the local `configurations/` directory

## CI/CD Strategy

This monorepo is designed for path-based automation:

- changes in `infrastructure/` trigger Terraform plan/apply
- changes in `agent-core/` rebuild and deploy the core runtime
- changes in a specific `mcp-servers/<tool>/` folder deploy only that tool
- changes in `configurations/` validate schemas and sync configuration to Cosmos DB

## Status

This scaffold provides the initial repository structure, starter service code, sample configurations, and workflow placeholders needed to evolve the platform.
