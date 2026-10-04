from pydantic import BaseModel
from app.schemas.user import User

class DemoLoginResponse(BaseModel):
    token: str
    user: User
