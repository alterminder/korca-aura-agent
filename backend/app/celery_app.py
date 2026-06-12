"""Celery application instance — imported by both worker and API routes."""

from celery import Celery

from app.config import settings

celery_app = Celery("korca", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=3600,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    timezone="UTC",
    enable_utc=True,
    # Match the previous 600-second job timeout: soft limit signals cleanup, hard kills
    task_soft_time_limit=570,
    task_time_limit=600,
)

celery_app.conf.beat_schedule = {
    "poll-teamwork-updates": {
        "task": "poll_teamwork_updates",
        "schedule": 60.0,
    },
}
