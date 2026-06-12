from fastapi import APIRouter
from pydantic import BaseModel

from app.services.notifications import get_notifications

router = APIRouter()


class Notification(BaseModel):
    type: str
    message: str
    status: str
    created_at: str


@router.get("/")
async def list_notifications(limit: int = 20) -> list[Notification]:
    return [Notification(**n) for n in await get_notifications(limit=limit)]
