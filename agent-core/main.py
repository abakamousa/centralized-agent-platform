import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from auth.context import RequestIdentity
from graph.builder import DynamicGraphRunner
from services.config_store import ConfigurationStore
from services.observability import ObservabilityClient


class AgentRequest(BaseModel):
    application_id: str
    input: str
    context: dict[str, Any] | None = None


app = FastAPI(title="Centralized Agent Core", version="0.1.0")

config_store = ConfigurationStore(os.getenv("APP_CONFIG_DIR", "/app/configurations"))
observability = ObservabilityClient(os.getenv("MLFLOW_TRACKING_URI"))
runner = DynamicGraphRunner(observability=observability)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/invoke")
async def invoke_agent(
    payload: AgentRequest,
    authorization: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> dict[str, Any]:
    if not authorization:
      raise HTTPException(status_code=401, detail="Missing Authorization header")

    identity = RequestIdentity(
        authorization=authorization,
        user_id=x_user_id or "anonymous",
    )
    app_config = config_store.load_application(payload.application_id)
    result = await runner.run(
        request=payload,
        identity=identity,
        app_config=app_config,
    )
    return result
