from pydantic import BaseModel


class RequestIdentity(BaseModel):
    authorization: str
    user_id: str
