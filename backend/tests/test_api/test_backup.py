import io
import json
import tarfile
from typing import get_args, get_origin, get_type_hints

import pytest

from app.api.routes import backup
from app.config import settings


class _FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    async def data(self):
        return self._rows

    async def single(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self):
        self.queries = []

    async def run(self, query, **params):
        self.queries.append((query, params))
        return _FakeResult()


class _FakeDbContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_create_backup_creates_tar_gz_with_pdfs_and_db_json(client, tmp_path, monkeypatch):
    # Mock settings storage path
    monkeypatch.setattr(settings, "backup_storage_path", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "pdf_storage_path", str(tmp_path / "pdfs"))

    # Create a dummy PDF in pdfs/
    pdfs_dir = tmp_path / "pdfs"
    pdfs_dir.mkdir()
    dummy_pdf = pdfs_dir / "document_1.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 dummy content")

    session = _FakeSession()
    monkeypatch.setattr(backup, "db_context", lambda: _FakeDbContext(session))

    # Trigger create backup via API
    resp = await client.post("/api/backup/create")
    assert resp.status_code == 200

    # Read SSE progress response
    sse_lines = resp.text.split("\n")
    done_event = [
        line
        for line in sse_lines
        if "event: done" in line or 'event": "done' in line or "done" in line
    ]
    assert len(done_event) > 0

    # Locate created tar.gz file
    backups_dir = tmp_path / "backups"
    tarball_files = list(backups_dir.glob("korca_backup_*.tar.gz"))
    assert len(tarball_files) == 1
    tarball_path = tarball_files[0]

    # Verify tarball content
    with tarfile.open(tarball_path, "r:gz") as tar:
        members = tar.getnames()
        assert "db_backup.json" in members
        assert "pdfs/document_1.pdf" in members

        # Extract db_backup.json and verify stats structure
        fileobj = tar.extractfile("db_backup.json")
        payload = json.loads(fileobj.read().decode("utf-8"))
        assert payload["version"] == 1
        assert "stats" in payload
        assert "nodes" in payload
        assert "relationships" in payload


@pytest.mark.asyncio
async def test_list_backups_reads_metadata_from_tarball(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "backup_storage_path", str(tmp_path / "backups"))
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()

    # Write a fake tarball backup manually
    tarball_path = backups_dir / "korca_backup_2026-05-26_12-00-00.tar.gz"
    payload = {
        "created_at": "2026-05-26T12:00:00Z",
        "stats": {"tickets": 42, "users": 5},
        "nodes": {},
        "relationships": {},
    }
    with tarfile.open(tarball_path, "w:gz") as tar:
        json_data = json.dumps(payload).encode("utf-8")
        info = tarfile.TarInfo(name="db_backup.json")
        info.size = len(json_data)
        tar.addfile(info, io.BytesIO(json_data))

    resp = await client.get("/api/backup/list")
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert results[0]["filename"] == "korca_backup_2026-05-26_12-00-00.tar.gz"
    assert results[0]["created_at"] == "2026-05-26T12:00:00Z"
    assert results[0]["stats"] == {"tickets": 42, "users": 5}
    assert isinstance(results[0]["size_kb"], int)


def _return_annotation_name(function) -> str:
    annotation = get_type_hints(function)["return"]
    origin = get_origin(annotation)
    if origin is list:
        (item_type,) = get_args(annotation)
        return f"list[{item_type.__name__}]"
    if hasattr(annotation, "__name__"):
        return annotation.__name__
    return str(annotation).replace("app.api.routes.backup.", "")


def test_backup_route_handlers_have_typed_response_models():
    assert _return_annotation_name(backup.list_backups) == "list[BackupResponse]"
    assert _return_annotation_name(backup.upload_backup) == "BackupResponse"
    assert _return_annotation_name(backup.delete_backup) == "BackupDeletedResponse"


@pytest.mark.asyncio
async def test_delete_backup_removes_file(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "backup_storage_path", str(tmp_path / "backups"))
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    target = backups_dir / "korca_backup_2026-05-26_12-00-00.tar.gz"
    target.write_bytes(b"dummy")

    resp = await client.delete("/api/backup/korca_backup_2026-05-26_12-00-00.tar.gz")

    assert resp.status_code == 200
    assert resp.json() == {"deleted": "korca_backup_2026-05-26_12-00-00.tar.gz"}
    assert not target.exists()


@pytest.mark.asyncio
async def test_delete_backup_returns_404_when_missing(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "backup_storage_path", str(tmp_path / "backups"))
    (tmp_path / "backups").mkdir()

    resp = await client.delete("/api/backup/korca_backup_2026-05-26_12-00-00.tar.gz")

    assert resp.status_code == 404


def test_backup_response_coerces_non_dict_stats():
    # A malformed/legacy backup with null or non-object stats must not fail
    # response validation — it normalizes to {}.
    base = {"filename": "korca_backup_x.tar.gz", "size_kb": 5}
    assert backup.BackupResponse.model_validate({**base, "stats": None}).stats == {}
    assert backup.BackupResponse.model_validate({**base, "stats": "weird"}).stats == {}
    assert backup.BackupResponse.model_validate(base).stats == {}


@pytest.mark.asyncio
async def test_upload_backup_validates_structure(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "backup_storage_path", str(tmp_path / "backups"))
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    # 1. Test invalid file extension
    resp = await client.post(
        "/api/backup/upload", files={"file": ("korca_backup.json", b"{}", "application/json")}
    )
    assert resp.status_code == 400
    assert "Only .tar.gz" in resp.json()["detail"]

    # 2. Test invalid prefix name
    resp = await client.post(
        "/api/backup/upload", files={"file": ("invalid_name.tar.gz", b"fake", "application/gzip")}
    )
    assert resp.status_code == 400
    assert "Filename must start with" in resp.json()["detail"]

    # 3. Test invalid tarball structure (missing db_backup.json)
    empty_tarball = io.BytesIO()
    with tarfile.open(fileobj=empty_tarball, mode="w:gz"):
        pass
    empty_tarball.seek(0)
    resp = await client.post(
        "/api/backup/upload",
        files={"file": ("korca_backup_invalid.tar.gz", empty_tarball.read(), "application/gzip")},
    )
    assert resp.status_code == 400
    assert "Invalid backup file" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_restore_backup_restores_pdfs_and_unwinds_db(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "backup_storage_path", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "pdf_storage_path", str(tmp_path / "pdfs"))

    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    pdfs_dir = tmp_path / "pdfs"
    pdfs_dir.mkdir()

    # Create dummy tarball containing db_backup.json and pdfs/doc.pdf
    tarball_path = backups_dir / "korca_backup_restore_test.tar.gz"
    payload = {
        "nodes": {
            "tickets": [{"id": 101, "subject": "Test ticket"}],
            "users": [{"email": "test@user.com", "name": "Test User"}],
        },
        "relationships": {
            "routed_to": [
                {
                    "from_email": "test@user.com",
                    "ticket_id": 101,
                    "props": {"method": "Aura"},
                }
            ],
        },
    }
    with tarfile.open(tarball_path, "w:gz") as tar:
        json_data = json.dumps(payload).encode("utf-8")
        info = tarfile.TarInfo(name="db_backup.json")
        info.size = len(json_data)
        tar.addfile(info, io.BytesIO(json_data))

        pdf_content = b"%PDF-1.4 dummy pdf bytes"
        pdf_info = tarfile.TarInfo(name="pdfs/doc_101.pdf")
        pdf_info.size = len(pdf_content)
        tar.addfile(pdf_info, io.BytesIO(pdf_content))

    session = _FakeSession()
    monkeypatch.setattr(backup, "db_context", lambda: _FakeDbContext(session))

    resp = await client.post("/api/backup/restore/korca_backup_restore_test.tar.gz")
    assert resp.status_code == 200

    # Ensure progress completed successfully
    assert "done" in resp.text

    # Verify PDF was physically extracted
    restored_pdf = pdfs_dir / "doc_101.pdf"
    assert restored_pdf.exists()
    assert restored_pdf.read_bytes() == b"%PDF-1.4 dummy pdf bytes"

    # Verify Cypher batch UNWIND statements were executed
    queries_run = [q[0] for q in session.queries]
    assert any("UNWIND $batch AS t" in q for q in queries_run)
    assert any("UNWIND $batch AS u" in q for q in queries_run)
    assert any("UNWIND $batch AS rel" in q for q in queries_run)


@pytest.mark.asyncio
async def test_restore_backup_rejects_invalid_archived_pdf(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "backup_storage_path", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "pdf_storage_path", str(tmp_path / "pdfs"))

    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    pdfs_dir = tmp_path / "pdfs"
    pdfs_dir.mkdir()

    tarball_path = backups_dir / "korca_backup_invalid_pdf.tar.gz"
    payload = {"nodes": {"tickets": []}, "relationships": {}}
    with tarfile.open(tarball_path, "w:gz") as tar:
        json_data = json.dumps(payload).encode("utf-8")
        info = tarfile.TarInfo(name="db_backup.json")
        info.size = len(json_data)
        tar.addfile(info, io.BytesIO(json_data))

        bad_content = b"not a pdf"
        bad_info = tarfile.TarInfo(name="pdfs/bad.pdf")
        bad_info.size = len(bad_content)
        tar.addfile(bad_info, io.BytesIO(bad_content))

    session = _FakeSession()
    monkeypatch.setattr(backup, "db_context", lambda: _FakeDbContext(session))

    resp = await client.post("/api/backup/restore/korca_backup_invalid_pdf.tar.gz")

    assert resp.status_code == 200
    assert '"event": "error"' in resp.text
    assert "not a valid PDF" in resp.text
    assert not (pdfs_dir / "bad.pdf").exists()
    assert session.queries == []


@pytest.mark.asyncio
async def test_restore_backup_does_not_overwrite_different_existing_pdf(
    client, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "backup_storage_path", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "pdf_storage_path", str(tmp_path / "pdfs"))

    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    pdfs_dir = tmp_path / "pdfs"
    pdfs_dir.mkdir()
    existing_pdf = pdfs_dir / "doc_101.pdf"
    existing_pdf.write_bytes(b"%PDF-1.4 existing bytes")

    tarball_path = backups_dir / "korca_backup_overwrite_pdf.tar.gz"
    payload = {"nodes": {"tickets": []}, "relationships": {}}
    with tarfile.open(tarball_path, "w:gz") as tar:
        json_data = json.dumps(payload).encode("utf-8")
        info = tarfile.TarInfo(name="db_backup.json")
        info.size = len(json_data)
        tar.addfile(info, io.BytesIO(json_data))

        new_content = b"%PDF-1.4 different bytes"
        pdf_info = tarfile.TarInfo(name="pdfs/doc_101.pdf")
        pdf_info.size = len(new_content)
        tar.addfile(pdf_info, io.BytesIO(new_content))

    session = _FakeSession()
    monkeypatch.setattr(backup, "db_context", lambda: _FakeDbContext(session))

    resp = await client.post("/api/backup/restore/korca_backup_overwrite_pdf.tar.gz")

    assert resp.status_code == 200
    assert '"event": "error"' in resp.text
    assert "already exists" in resp.text
    assert existing_pdf.read_bytes() == b"%PDF-1.4 existing bytes"
    assert session.queries == []


@pytest.mark.asyncio
async def test_restore_backup_uses_unwind_batches_for_large_node_sets(
    client, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "backup_storage_path", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "pdf_storage_path", str(tmp_path / "pdfs"))

    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    (tmp_path / "pdfs").mkdir()
    filename = "korca_backup_batch_nodes.tar.gz"
    tickets = [{"id": str(i), "subject": f"Ticket {i}"} for i in range(205)]
    tickets.append({"subject": "missing id"})
    payload = {
        "stats": {"tickets": len(tickets)},
        "nodes": {
            "tickets": tickets,
            "users": [],
            "clients": [],
            "skills": [],
            "blocked_tickets": [],
            "sync_states": [],
        },
        "relationships": {},
    }
    with tarfile.open(backups_dir / filename, "w:gz") as tar:
        json_data = json.dumps(payload).encode("utf-8")
        info = tarfile.TarInfo(name="db_backup.json")
        info.size = len(json_data)
        tar.addfile(info, io.BytesIO(json_data))

    session = _FakeSession()
    monkeypatch.setattr(backup, "db_context", lambda: _FakeDbContext(session))

    resp = await client.post(f"/api/backup/restore/{filename}")

    assert resp.status_code == 200
    assert "done" in resp.text
    ticket_calls = [
        params["batch"] for query, params in session.queries if "UNWIND $batch AS t" in query
    ]
    assert [len(batch) for batch in ticket_calls] == [100, 100, 5]
    assert all(ticket.get("id") is not None for batch in ticket_calls for ticket in batch)


@pytest.mark.asyncio
async def test_restore_backup_uses_unwind_batches_for_relationships(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "backup_storage_path", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "pdf_storage_path", str(tmp_path / "pdfs"))

    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    (tmp_path / "pdfs").mkdir()
    filename = "korca_backup_batch_relationships.tar.gz"
    assigned_to = [
        {
            "from_email": f"user{i}@example.com",
            "ticket_id": str(i),
            "props": {"source": "backup"},
        }
        for i in range(101)
    ]
    assigned_to.append({"from_email": "missing-ticket@example.com"})
    payload = {
        "stats": {"relationships": {"assigned_to": len(assigned_to)}},
        "nodes": {
            "tickets": [],
            "users": [],
            "clients": [],
            "skills": [],
            "blocked_tickets": [],
            "sync_states": [],
        },
        "relationships": {"assigned_to": assigned_to},
    }
    with tarfile.open(backups_dir / filename, "w:gz") as tar:
        json_data = json.dumps(payload).encode("utf-8")
        info = tarfile.TarInfo(name="db_backup.json")
        info.size = len(json_data)
        tar.addfile(info, io.BytesIO(json_data))

    session = _FakeSession()
    monkeypatch.setattr(backup, "db_context", lambda: _FakeDbContext(session))

    resp = await client.post(f"/api/backup/restore/{filename}")

    assert resp.status_code == 200
    assert "done" in resp.text
    assigned_calls = [
        params["batch"]
        for query, params in session.queries
        if "MERGE (u)-[r:ASSIGNED_TO]->(t)" in query
    ]
    assert [len(batch) for batch in assigned_calls] == [100, 1]
    assert all(rel.get("ticket_id") is not None for batch in assigned_calls for rel in batch)
