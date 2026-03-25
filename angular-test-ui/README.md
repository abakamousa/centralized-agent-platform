# Angular Test UI

This Angular app provides a lightweight playground for testing `agent-core`.

## Features

- select a saved app definition from the backend
- inspect the loaded YAML config
- paste a YAML app config and run it in preview mode
- send `session_id`, optional `thread_id`, and user input
- attach an Auth0 bearer token
- inspect raw JSON responses including memory and guardrail information

## Run

```bash
cd angular-test-ui
npm install
npm start
```

The Angular dev server runs on `http://localhost:4200` and proxies `/api` calls to `http://localhost:8000`.

Make sure `agent-core` is already running locally before using the UI.
