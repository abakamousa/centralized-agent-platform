from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel


class InvokeRequest(BaseModel):
    tool: str
    query: str


app = FastAPI(title="MCP AWS S3", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/invoke")
def invoke(
    payload: InvokeRequest,
    authorization: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> dict[str, str]:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    return {
        "tool": payload.tool,
        "status": "success",
        "message": f"S3 tool handled query for {x_user_id or 'unknown-user'}",
    }
