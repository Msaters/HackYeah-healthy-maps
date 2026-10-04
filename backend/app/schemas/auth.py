from pydantic import BaseModel
from backend.app.schemas.user import User

class DemoLoginResponse(BaseModel):
    token: str
    user: User
