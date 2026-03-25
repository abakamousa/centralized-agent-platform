# App Definitions

This directory contains application-specific YAML definitions for the centralized agent platform.

Each file maps an `application_id` to:

- runtime metadata and system prompts
- workflow layout and node sequencing
- allowed MCP servers and tool permissions

Workflow nodes are executed from `workflow.entrypoint` and can declare:

- `type`: the node handler to execute, such as `classifier`, `tool`, or `llm`
- `next`: the next node in the graph
- `tool`: the tool name to invoke for `tool` nodes
- `prompt`: response guidance for `llm` nodes
- `routes`: optional keyword-based branching for `classifier` nodes

These files are validated against the schema in `configurations/schemas/` before being synced to Cosmos DB.
