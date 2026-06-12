import asyncio
import pytest

from app import worker


class _FakeDbContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_generate_teamwork_expert_skill_clouds_saves_generated_skills(monkeypatch):
    session = object()
    experts = [
        {"id": "user_example", "name": "Example Expert", "email": "expert@example.com"},
        {"id": "user_empty", "name": "Empty Expert", "email": "empty@example.com"},
    ]
    saved = []

    async def fake_list_experts(_session):
        return experts

    async def fake_summaries(_session, user_id):
        if user_id == "user_empty":
            return []
        return ["Customer needed DNS and Cloudflare setup."]

    async def fake_generate(name, summaries):
        assert name == "Example Expert"
        assert summaries == ["Customer needed DNS and Cloudflare setup."]
        return ["dns configuration", "cloudflare"]

    async def fake_embeddings(skills):
        assert skills == ["dns configuration", "cloudflare"]
        return [[0.1], [0.2]]

    async def fake_update(_session, user_id, **kwargs):
        saved.append((user_id, kwargs))
        return True

    invalidated = []

    async def fake_invalidate(*keys):
        invalidated.extend(keys)

    progress_calls = []

    async def fake_get_progress():
        await asyncio.sleep(0)
        progress_calls.append("get")
        from app.services.teamwork_import_status import TeamworkImportProgress
        return TeamworkImportProgress(status="completed", message="Import finished.")

    async def fake_clear_progress():
        await asyncio.sleep(0)
        progress_calls.append("clear")

    monkeypatch.setattr("app.worker.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr(
        "app.worker.queries.list_teamwork_experts_for_skill_generation",
        fake_list_experts,
    )
    monkeypatch.setattr("app.worker.queries.get_expert_ticket_summaries", fake_summaries)
    monkeypatch.setattr("app.worker.llm_svc.generate_expert_skills", fake_generate)
    monkeypatch.setattr("app.worker.embed_svc.generate_embeddings", fake_embeddings)
    monkeypatch.setattr("app.worker.queries.update_user_profile", fake_update)
    monkeypatch.setattr("app.worker.invalidate_cache", fake_invalidate)
    monkeypatch.setattr("app.worker.get_progress", fake_get_progress)
    monkeypatch.setattr("app.worker.clear_progress", fake_clear_progress)

    result = await worker._generate_teamwork_expert_skill_clouds()

    assert result == {"experts_seen": 2, "generated": 1, "skipped": 1, "failed": 0}
    assert invalidated == ["korca:cache:experts"]
    assert progress_calls == ["get", "clear"]
    assert saved == [
        (
            "user_example",
            {
                "department": None,
                "title": None,
                "manager_email": None,
                "skills": ["dns configuration", "cloudflare"],
                "skill_embeddings": {
                    "dns configuration": [0.1],
                    "cloudflare": [0.2],
                },
            },
        )
    ]


@pytest.mark.asyncio
async def test_generate_teamwork_expert_skill_clouds_does_not_clear_running_progress(monkeypatch):
    session = object()

    async def fake_list_experts(_session):
        await asyncio.sleep(0)
        return []

    progress_calls = []

    async def fake_get_progress():
        await asyncio.sleep(0)
        progress_calls.append("get")
        from app.services.teamwork_import_status import TeamworkImportProgress
        return TeamworkImportProgress(status="running", message="Import running...")

    async def fake_clear_progress():
        await asyncio.sleep(0)
        progress_calls.append("clear")

    monkeypatch.setattr("app.worker.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr(
        "app.worker.queries.list_teamwork_experts_for_skill_generation",
        fake_list_experts,
    )
    monkeypatch.setattr("app.worker.get_progress", fake_get_progress)
    monkeypatch.setattr("app.worker.clear_progress", fake_clear_progress)

    result = await worker._generate_teamwork_expert_skill_clouds()

    assert result == {"experts_seen": 0, "generated": 0, "skipped": 0, "failed": 0}
    assert progress_calls == ["get"]

