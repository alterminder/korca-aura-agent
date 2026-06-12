from pydantic import BaseModel


class User(BaseModel):
    id: str
    email: str
    name: str
    department: str | None = None
    certifications: list[str] = []
