from pydantic import BaseModel


class RequestIdentity(BaseModel):
    authorization: str
    user_id: str
    session_id: str
    permissions: list[str] = []
    issuer: str
    audience: list[str] = []
    subject: str
    auth_provider: str = "auth0"
    entra_tenant_id: str | None = None
    claims: dict[str, object] = {}
