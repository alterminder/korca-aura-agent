"""
Graph backup and restore routes.

Backup  — read-only export of all nodes + relationships to a timestamped JSON file on PV.
Restore — replays the JSON using MERGE only. Never deletes anything from the graph.
"""

import io
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiofiles
import structlog
from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.db.connection import db_context
from app.exceptions import DomainValidationError

logger = structlog.get_logger()
router = APIRouter()

MAX_BACKUPS = 10
BACKUP_VERSION = 1
_DB_BACKUP_JSON = "db_backup.json"
_BACKUP_NOT_FOUND = "Backup not found"


class BackupResponse(BaseModel):
    """A stored backup archive's metadata (list item and upload result share
    this shape). `stats` is a freeform node/edge summary from the backup JSON."""

    filename: str
    created_at: str | None = None
    size_kb: int
    stats: dict[str, Any] = Field(default_factory=dict)

    @field_validator("stats", mode="before")
    @classmethod
    def _coerce_stats(cls, value: Any) -> dict[str, Any]:
        # A backup's JSON may carry null or a non-object stats; normalize to {}
        # so a malformed/legacy archive can't fail response validation.
        return value if isinstance(value, dict) else {}


class BackupDeletedResponse(BaseModel):
    deleted: str


def _write_backup_tar(filepath: Path, payload: dict[str, Any]) -> None:
    """Write payload to a gzipped tar at filepath, atomically via a .tmp file."""
    temp = filepath.with_suffix(".tmp")
    try:
        with tarfile.open(temp, "w:gz") as tar:
            json_data = json.dumps(payload, default=str).encode("utf-8")
            json_info = tarfile.TarInfo(name=_DB_BACKUP_JSON)
            json_info.size = len(json_data)
            tar.addfile(json_info, io.BytesIO(json_data))
            pdf_dir = Path(settings.pdf_storage_path)
            if pdf_dir.exists():
                for f in pdf_dir.iterdir():
                    if f.is_file() and f.suffix.lower() == ".pdf":
                        tar.add(f, arcname=f"pdfs/{f.name}")
        temp.rename(filepath)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _progress(message: str, step: int, total_steps: int = 8) -> str:
    return _sse(
        "progress",
        {"message": message, "step": step, "total_steps": total_steps},
    )


def _validate_and_extract_pdf(
    tar: tarfile.TarFile, member: tarfile.TarInfo, dest_dir_abs: Path
) -> tuple[Path, bytes] | None:
    if not member.name.startswith("pdfs/") or not member.isreg():
        return None

    filename = Path(member.name).name
    if not filename or Path(filename).suffix.lower() != ".pdf":
        raise ValueError(f"Invalid PDF backup member: {member.name}")

    fileobj = tar.extractfile(member)
    if not fileobj:
        raise ValueError(f"Could not read archived PDF: {filename}")
    content = fileobj.read()
    if not content.startswith(b"%PDF"):
        raise ValueError(f"Archived PDF {filename} is not a valid PDF")

    dest_file = (dest_dir_abs / filename).resolve()
    try:
        dest_file.relative_to(dest_dir_abs)
    except ValueError as exc:
        raise ValueError(f"Path traversal detected in backup member: {member.name}") from exc

    if dest_file.exists() and dest_file.read_bytes() != content:
        raise ValueError(f"PDF {filename} already exists with different content")

    return dest_file, content


def _load_pdf_restore_files(tar: tarfile.TarFile, dest_dir: Path) -> list[tuple[Path, bytes]]:
    files: list[tuple[Path, bytes]] = []
    dest_dir_abs = dest_dir.resolve()
    for member in tar.getmembers():
        res = _validate_and_extract_pdf(tar, member, dest_dir_abs)
        if res:
            files.append(res)
    return files


def _write_pdf_restore_files(files: list[tuple[Path, bytes]]) -> None:
    for dest_file, content in files:
        if not dest_file.exists():
            dest_file.write_bytes(content)


def _backup_dir() -> Path:
    d = Path(settings.backup_storage_path)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _secure_backup_path(filename: str) -> Path:
    """Resolve and validate a backup filename to prevent any path traversal or injection.

    Enforces that the final path is strictly located under the configured backup directory.
    """
    import re

    # Strictly validate that the filename is only composed of safe characters
    # (alphanumeric, dashes, and underscores) with the expected prefix and extension.
    match = re.match(r"^korca_backup_([a-zA-Z0-9_-]+)\.tar\.gz$", filename)
    if not match:
        # Prevent path traversal characters explicitly to maintain detailed exceptions
        if "/" in filename or "\\" in filename:
            raise DomainValidationError("Invalid filename")
        if not filename.startswith("korca_backup_"):
            raise DomainValidationError("Filename must start with korca_backup_")
        raise DomainValidationError("Invalid filename format")

    # Reconstruct the string from scratch using the validated safe match group
    # to completely break the taint analysis data flow.
    safe_filename = f"korca_backup_{match.group(1)}.tar.gz"

    backup_dir_abs = _backup_dir().resolve()
    filepath = (backup_dir_abs / safe_filename).resolve()

    try:
        filepath.relative_to(backup_dir_abs)
    except ValueError as exc:
        raise DomainValidationError("Path traversal detected in backup filename") from exc

    return filepath


def _prune_old_backups() -> None:
    """Keep only the MAX_BACKUPS most recent files."""
    files = sorted(_backup_dir().glob("korca_backup_*.tar.gz"), key=lambda f: f.stat().st_mtime)
    for old in files[:-MAX_BACKUPS]:
        old.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse(event: str, data: dict) -> str:
    return f"data: {json.dumps({'event': event, **data})}\n\n"


async def _fetch_all(query: str) -> list[dict]:
    """Open a session, run a read query, and return all rows as plain dicts."""
    async with db_context() as session:
        result = await session.run(query)
        return list(await result.data())


_RESTORE_BATCH_SIZE = 100


async def _restore_batched(query: str, items: list[dict]) -> None:
    """Apply `query` to `items` in fixed-size UNWIND batches."""
    for i in range(0, len(items), _RESTORE_BATCH_SIZE):
        async with db_context() as session:
            await session.run(query, batch=items[i : i + _RESTORE_BATCH_SIZE])


def _relationship_payload(rows: list[dict]) -> list[dict]:
    """Project routed_to / assigned_to rows into a uniform restore payload."""
    return [
        {
            "from_email": r["from_email"],
            "ticket_id": r["ticket_id"],
            "props": r.get("props") or {},
        }
        for r in rows
        if r.get("from_email") and r.get("ticket_id") is not None
    ]


# ---------------------------------------------------------------------------
# POST /backup/create  — stream progress, write file
# ---------------------------------------------------------------------------


@router.post("/create")
async def create_backup() -> StreamingResponse:
    async def _stream():
        try:
            yield _progress("Exporting tickets…", 1)
            tickets = [
                row["props"]
                for row in await _fetch_all("MATCH (t:Ticket) RETURN properties(t) AS props")
            ]

            yield _progress(f"Exported {len(tickets)} tickets. Exporting users…", 2)
            users = [
                row["props"]
                for row in await _fetch_all("MATCH (u:User) RETURN properties(u) AS props")
            ]

            yield _progress(f"Exported {len(users)} users. Exporting clients…", 3)
            clients = [
                row["props"]
                for row in await _fetch_all("MATCH (c:Client) RETURN properties(c) AS props")
            ]

            yield _progress("Exporting skills, sync state, blocklist…", 4)
            skills = [
                row["props"]
                for row in await _fetch_all("MATCH (s:Skill) RETURN properties(s) AS props")
            ]
            blocked = [
                row["props"]
                for row in await _fetch_all("MATCH (b:BlockedTicket) RETURN properties(b) AS props")
            ]
            sync_states = [
                row["props"]
                for row in await _fetch_all("MATCH (ss:SyncState) RETURN properties(ss) AS props")
            ]

            yield _progress("Exporting relationships…", 5)
            routed_to = [
                dict(row)
                for row in await _fetch_all(
                    "MATCH (u:User)-[rel:ROUTED_TO]->(t:Ticket) "
                    "RETURN u.email AS from_email, t.id AS ticket_id, properties(rel) AS props"
                )
            ]
            assigned_to = [
                dict(row)
                for row in await _fetch_all(
                    "MATCH (u:User)-[rel:ASSIGNED_TO]->(t:Ticket) "
                    "RETURN u.email AS from_email, t.id AS ticket_id, properties(rel) AS props"
                )
            ]
            from_client = [
                dict(row)
                for row in await _fetch_all(
                    "MATCH (t:Ticket)-[:FROM]->(c:Client) "
                    "RETURN t.id AS ticket_id, c.domain AS client_domain"
                )
            ]
            works_for = [
                dict(row)
                for row in await _fetch_all(
                    "MATCH (child:Client)-[:WORKS_FOR]->(parent:Client) "
                    "RETURN child.domain AS child_domain, parent.domain AS parent_domain"
                )
            ]
            has_skill = [
                dict(row)
                for row in await _fetch_all(
                    "MATCH (u:User)-[:HAS_SKILL]->(s:Skill) "
                    "RETURN u.email AS user_email, s.name AS skill_name"
                )
            ]
            reports_to = [
                dict(row)
                for row in await _fetch_all(
                    "MATCH (a:User)-[:REPORTS_TO]->(b:User) "
                    "RETURN a.email AS from_email, b.email AS to_email"
                )
            ]

            yield _progress("Writing backup file…", 6)

            payload = {
                "version": BACKUP_VERSION,
                "created_at": datetime.now(UTC).isoformat(),
                "stats": {
                    "tickets": len(tickets),
                    "users": len(users),
                    "clients": len(clients),
                    "skills": len(skills),
                    "blocked_tickets": len(blocked),
                    "sync_states": len(sync_states),
                    "relationships": {
                        "routed_to": len(routed_to),
                        "assigned_to": len(assigned_to),
                        "from_client": len(from_client),
                        "works_for": len(works_for),
                        "has_skill": len(has_skill),
                        "reports_to": len(reports_to),
                    },
                },
                "nodes": {
                    "tickets": tickets,
                    "users": users,
                    "clients": clients,
                    "skills": skills,
                    "blocked_tickets": blocked,
                    "sync_states": sync_states,
                },
                "relationships": {
                    "routed_to": routed_to,
                    "assigned_to": assigned_to,
                    "from_client": from_client,
                    "works_for": works_for,
                    "has_skill": has_skill,
                    "reports_to": reports_to,
                },
            }

            ts = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"korca_backup_{ts}.tar.gz"
            filepath = _backup_dir() / filename

            _write_backup_tar(filepath, payload)

            _prune_old_backups()

            size_kb = round(filepath.stat().st_size / 1024)

            yield _progress("Done.", 8)
            yield _sse(
                "done",
                {
                    "filename": filename,
                    "stats": payload["stats"],
                    "size_kb": size_kb,
                },
            )

            logger.info("backup_created", filename=filename, tickets=len(tickets), size_kb=size_kb)

        except Exception as exc:
            logger.error("backup_failed", error=str(exc))
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# GET /backup/list
# ---------------------------------------------------------------------------


@router.get("/list")
async def list_backups() -> list[BackupResponse]:
    files = sorted(
        _backup_dir().glob("korca_backup_*.tar.gz"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    result = []
    for f in files:
        try:
            with tarfile.open(f, "r:gz") as tar:
                member = tar.getmember(_DB_BACKUP_JSON)
                fileobj = tar.extractfile(member)
                if not fileobj:
                    raise ValueError(f"{_DB_BACKUP_JSON} not found")
                data = json.loads(fileobj.read().decode("utf-8"))
            result.append(
                {
                    "filename": f.name,
                    "created_at": data.get("created_at"),
                    "size_kb": round(f.stat().st_size / 1024),
                    "stats": data.get("stats", {}),
                }
            )
        except Exception:
            result.append(
                {
                    "filename": f.name,
                    "created_at": None,
                    "size_kb": round(f.stat().st_size / 1024),
                    "stats": {},
                }
            )
    return [BackupResponse.model_validate(item) for item in result]


# ---------------------------------------------------------------------------
# POST /backup/upload  — upload a local backup file to the PV
# ---------------------------------------------------------------------------


@router.post(
    "/upload",
    responses={
        400: {"description": "Only .tar.gz backup files are accepted or path traversal detected"},
    },
)
async def upload_backup(file: UploadFile) -> BackupResponse:
    if not file.filename or not file.filename.endswith(".tar.gz"):
        raise HTTPException(status_code=400, detail="Only .tar.gz backup files are accepted")

    # Enforce basic validation check on the filename structure without using it for path construction
    filename_check = Path(file.filename).name
    if not filename_check.startswith("korca_backup_"):
        raise HTTPException(status_code=400, detail="Filename must start with korca_backup_")

    content = await file.read()

    # Validate it's parseable tar.gz with expected db_backup.json structure
    try:
        with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
            member = tar.getmember(_DB_BACKUP_JSON)
            fileobj = tar.extractfile(member)
            if not fileobj:
                raise ValueError(f"{_DB_BACKUP_JSON} not found")
            parsed = json.loads(fileobj.read().decode("utf-8"))
            if "nodes" not in parsed or "relationships" not in parsed:
                raise ValueError("Missing nodes or relationships keys")
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid backup file — not a valid Korca tar.gz backup",
        )

    # Reconstruct a completely safe filename from the current server time
    # to guarantee absolute isolation from any user-controlled string or metadata taint.
    import datetime

    backup_time = datetime.datetime.now(datetime.UTC)
    ts = backup_time.strftime("%Y-%m-%d_%H-%M-%S")
    safe_name = f"korca_backup_{ts}.tar.gz"
    dest = _secure_backup_path(safe_name)

    async with aiofiles.open(dest, "wb") as f:
        await f.write(content)
    _prune_old_backups()

    size_kb = round(dest.stat().st_size / 1024)
    logger.info("backup_uploaded", filename=safe_name, size_kb=size_kb)

    return BackupResponse(
        filename=safe_name,
        size_kb=size_kb,
        stats=parsed.get("stats", {}),
        created_at=parsed.get("created_at"),
    )


# ---------------------------------------------------------------------------
# GET /backup/download/{filename}
# ---------------------------------------------------------------------------


@router.get(
    "/download/{filename}",
    responses={
        400: {"description": "Invalid filename or path traversal detected"},
        404: {"description": _BACKUP_NOT_FOUND},
    },
)
async def download_backup(filename: str) -> FileResponse:
    filepath = _secure_backup_path(filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=_BACKUP_NOT_FOUND)
    return FileResponse(filepath, filename=filename, media_type="application/gzip")


# ---------------------------------------------------------------------------
# DELETE /backup/{filename}
# ---------------------------------------------------------------------------


@router.delete(
    "/{filename}",
    responses={
        400: {"description": "Invalid filename or path traversal detected"},
        404: {"description": _BACKUP_NOT_FOUND},
    },
)
async def delete_backup(filename: str) -> BackupDeletedResponse:
    filepath = _secure_backup_path(filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=_BACKUP_NOT_FOUND)
    filepath.unlink()
    return BackupDeletedResponse(deleted=filename)


# ---------------------------------------------------------------------------
# POST /backup/restore/{filename}  — MERGE only, never deletes
# ---------------------------------------------------------------------------


@router.post(
    "/restore/{filename}",
    responses={
        400: {"description": "Invalid filename, path traversal, or corrupt backup"},
        404: {"description": _BACKUP_NOT_FOUND},
    },
)
async def restore_backup(filename: str) -> StreamingResponse:
    filepath = _secure_backup_path(filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=_BACKUP_NOT_FOUND)

    async def _stream():
        try:
            with tarfile.open(filepath, "r:gz") as tar:
                # 1. Extract db_backup.json
                json_member = tar.getmember(_DB_BACKUP_JSON)
                fileobj = tar.extractfile(json_member)
                if not fileobj:
                    raise ValueError(f"{_DB_BACKUP_JSON} not found in archive")
                payload = json.loads(fileobj.read().decode("utf-8"))

                # 2. Validate PDF files before any restore side effects
                dest_dir = Path(settings.pdf_storage_path)
                dest_dir.mkdir(parents=True, exist_ok=True)
                pdf_files = _load_pdf_restore_files(tar, dest_dir)
                _write_pdf_restore_files(pdf_files)
            nodes = payload.get("nodes", {})
            rels = payload.get("relationships", {})

            tickets = nodes.get("tickets", [])
            yield _progress(f"Restoring {len(tickets)} tickets…", 1)
            await _restore_batched(
                """
                UNWIND $batch AS t
                MERGE (ticket:Ticket {id: t.id})
                SET ticket += t
                """,
                [t for t in tickets if t.get("id") is not None],
            )

            users = nodes.get("users", [])
            yield _progress(f"Restoring {len(users)} users…", 2)
            await _restore_batched(
                """
                UNWIND $batch AS u
                MERGE (user:User {email: u.email})
                SET user += u
                """,
                [u for u in users if u.get("email")],
            )

            clients = nodes.get("clients", [])
            yield _progress(f"Restoring {len(clients)} clients…", 3)
            await _restore_batched(
                """
                UNWIND $batch AS c
                MERGE (client:Client {domain: c.domain})
                SET client += c
                """,
                [c for c in clients if c.get("domain")],
            )

            skills = nodes.get("skills", [])
            yield _progress(f"Restoring {len(skills)} skills, sync state, blocklist…", 4)
            await _restore_batched(
                """
                UNWIND $batch AS s
                MERGE (skill:Skill {name: s.name})
                SET skill += s
                """,
                [s for s in skills if s.get("name")],
            )
            await _restore_batched(
                "UNWIND $batch AS b MERGE (:BlockedTicket {id: b.id})",
                [b for b in nodes.get("blocked_tickets", []) if b.get("id") is not None],
            )
            await _restore_batched(
                """
                UNWIND $batch AS ss
                MERGE (state:SyncState {source: ss.source})
                SET state += ss
                """,
                [ss for ss in nodes.get("sync_states", []) if ss.get("source")],
            )

            yield _progress("Restoring relationships…", 5)
            await _restore_batched(
                """
                UNWIND $batch AS rel
                MATCH (u:User {email: rel.from_email})
                MATCH (t:Ticket)
                WHERE t.id = toString(rel.ticket_id) OR t.id = toInteger(rel.ticket_id)
                MERGE (u)-[r:ROUTED_TO]->(t)
                SET r += rel.props
                """,
                _relationship_payload(rels.get("routed_to", [])),
            )
            await _restore_batched(
                """
                UNWIND $batch AS rel
                MATCH (u:User {email: rel.from_email})
                MATCH (t:Ticket)
                WHERE t.id = toString(rel.ticket_id) OR t.id = toInteger(rel.ticket_id)
                MERGE (u)-[r:ASSIGNED_TO]->(t)
                SET r += rel.props
                """,
                _relationship_payload(rels.get("assigned_to", [])),
            )

            yield _progress("Restoring ticket→client and client hierarchy…", 6)
            await _restore_batched(
                """
                UNWIND $batch AS rel
                MATCH (t:Ticket)
                WHERE t.id = toString(rel.ticket_id) OR t.id = toInteger(rel.ticket_id)
                MATCH (c:Client {domain: rel.client_domain})
                MERGE (t)-[:FROM]->(c)
                """,
                [
                    r
                    for r in rels.get("from_client", [])
                    if r.get("ticket_id") is not None and r.get("client_domain")
                ],
            )
            await _restore_batched(
                """
                UNWIND $batch AS rel
                MATCH (child:Client {domain: rel.child_domain})
                MATCH (parent:Client {domain: rel.parent_domain})
                MERGE (child)-[:WORKS_FOR]->(parent)
                """,
                [
                    r
                    for r in rels.get("works_for", [])
                    if r.get("child_domain") and r.get("parent_domain")
                ],
            )

            yield _progress("Restoring user skills and hierarchy…", 7)
            await _restore_batched(
                """
                UNWIND $batch AS rel
                MATCH (u:User {email: rel.user_email})
                MATCH (s:Skill {name: rel.skill_name})
                MERGE (u)-[:HAS_SKILL]->(s)
                """,
                [
                    r
                    for r in rels.get("has_skill", [])
                    if r.get("user_email") and r.get("skill_name")
                ],
            )
            await _restore_batched(
                """
                UNWIND $batch AS rel
                MATCH (a:User {email: rel.from_email})
                MATCH (b:User {email: rel.to_email})
                MERGE (a)-[:REPORTS_TO]->(b)
                """,
                [
                    r
                    for r in rels.get("reports_to", [])
                    if r.get("from_email") and r.get("to_email")
                ],
            )

            stats = payload.get("stats", {})
            yield _progress("Done.", 8)
            yield _sse("done", {"stats": stats})

            logger.info("restore_complete", filename=filename, tickets=stats.get("tickets"))

        except Exception as exc:
            logger.error("restore_failed", filename=filename, error=str(exc))
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(_stream(), media_type="text/event-stream")
