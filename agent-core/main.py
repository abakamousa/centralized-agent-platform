import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from auth import Auth0TokenValidator
from graph.builder import DynamicGraphRunner
from services.config_store import ConfigurationStore
from services.observability import ObservabilityClient
from services.runtime_config import RuntimeConfig


class AgentRequest(BaseModel):
    application_id: str
    input: str
    session_id: str | None = None
    thread_id: str | None = None
    context: dict[str, Any] | None = None


app = FastAPI(title="Centralized Agent Core", version="0.1.0")

runtime_config = RuntimeConfig.load()
config_store = ConfigurationStore(os.getenv("APP_CONFIG_DIR", "/app/app"))
observability = ObservabilityClient(
    runtime_config.section("observability").get("mlflow_tracking_uri")
    or os.getenv("MLFLOW_TRACKING_URI")
)
token_validator = Auth0TokenValidator(runtime_config.section("auth0"))
runner = DynamicGraphRunner(
    observability=observability,
    foundry_config=runtime_config.section("foundry"),
    mcp_config=runtime_config.section("mcp"),
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/invoke")
async def invoke_agent(
    payload: AgentRequest,
    authorization: str | None = Header(default=None),
    x_session_id: str | None = Header(default=None),
) -> dict[str, Any]:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    identity = token_validator.validate(
        authorization,
        session_id=payload.session_id or x_session_id,
    )
    app_config = config_store.load_application(payload.application_id)
    result = await runner.run(
        request=payload,
        identity=identity,
        app_config=app_config,
    )
    return result
