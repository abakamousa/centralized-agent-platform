import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
import yaml

from auth import Auth0TokenValidator
from graph.builder import DynamicGraphRunner
from services.config_store import ConfigurationStore
from services.guardrails import GuardrailsService, PromptInjectionDetectedError
from services.observability import ObservabilityClient
from services.runtime_config import RuntimeConfig


class AgentRequest(BaseModel):
    application_id: str
    input: str
    session_id: str | None = None
    thread_id: str | None = None
    context: dict[str, Any] | None = None


class PreviewRequest(BaseModel):
    app_config_yaml: str
    input: str
    session_id: str | None = None
    thread_id: str | None = None
    context: dict[str, Any] | None = None


app = FastAPI(title="Centralized Agent Core", version="0.1.0")

runtime_config = RuntimeConfig.load()
config_store = ConfigurationStore(
    os.getenv("APP_CONFIG_DIR", "/app/app"),
    cosmos_config=runtime_config.section("cosmos"),
)
observability = ObservabilityClient(
    runtime_config.section("observability").get("mlflow_tracking_uri")
    or os.getenv("MLFLOW_TRACKING_URI")
)
token_validator = Auth0TokenValidator(runtime_config.section("auth0"))
guardrails = GuardrailsService(runtime_config.section("guardrails"))
runner = DynamicGraphRunner(
    observability=observability,
    foundry_config=runtime_config.section("foundry"),
    mcp_config=runtime_config.section("mcp"),
    cosmos_config=runtime_config.section("cosmos"),
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/apps")
def list_applications() -> dict[str, list[dict[str, Any]]]:
    return {"applications": config_store.list_applications()}


@app.get("/apps/{application_id}")
def get_application(application_id: str) -> dict[str, Any]:
    return config_store.load_application(application_id)


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
    try:
        guardrail_result = guardrails.process(payload.input)
    except PromptInjectionDetectedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    app_config = config_store.load_application(payload.application_id)
    sanitized_payload = payload.model_copy(update={"input": guardrail_result.sanitized_input})
    result = await runner.run(
        request=sanitized_payload,
        identity=identity,
        app_config=app_config,
    )
    result["guardrails"] = {
        "prompt_injection_detected": guardrail_result.prompt_injection_detected,
        "pii_detected": guardrail_result.pii_detected,
        "findings": guardrail_result.findings,
    }
    return result


@app.post("/preview/invoke")
async def preview_invoke_agent(
    payload: PreviewRequest,
    authorization: str | None = Header(default=None),
    x_session_id: str | None = Header(default=None),
) -> dict[str, Any]:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    identity = token_validator.validate(
        authorization,
        session_id=payload.session_id or x_session_id,
    )
    try:
        guardrail_result = guardrails.process(payload.input)
    except PromptInjectionDetectedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        app_config = yaml.safe_load(payload.app_config_yaml) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail="Invalid YAML app config") from exc

    application_id = app_config.get("application_id")
    if not application_id:
        raise HTTPException(status_code=400, detail="Preview config must define application_id")

    sanitized_payload = AgentRequest(
        application_id=str(application_id),
        input=guardrail_result.sanitized_input,
        session_id=payload.session_id,
        thread_id=payload.thread_id,
        context=payload.context,
    )
    result = await runner.run(
        request=sanitized_payload,
        identity=identity,
        app_config=app_config,
    )
    result["guardrails"] = {
        "prompt_injection_detected": guardrail_result.prompt_injection_detected,
        "pii_detected": guardrail_result.pii_detected,
        "findings": guardrail_result.findings,
    }
    result["preview"] = True
    return result
