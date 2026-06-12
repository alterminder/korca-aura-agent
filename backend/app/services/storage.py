import hashlib
import re
import shutil
from pathlib import Path

import aiofiles
import structlog
from fastapi import UploadFile

from app.config import settings
from app.exceptions import FileOversizedError

logger = structlog.get_logger()

# Document IDs are opaque tokens. Restricting them to this allowlist (no path
# separators, dots, or null bytes) prevents escape from the storage directory
# regardless of OS or symlink state, breaking the path-traversal taint flow.
_SAFE_ID = re.compile(r"\A[A-Za-z0-9_-]+\Z")


def get_pdf_path(document_id: str) -> Path:
    raw_id = document_id.rsplit(":", maxsplit=1)[-1]
    if not _SAFE_ID.match(raw_id):
        raise ValueError(f"Invalid document id: {document_id!r}")
    base = Path(settings.pdf_storage_path).resolve()
    candidate = (base / f"{raw_id}.pdf").resolve()
    if candidate.parent != base:
        raise ValueError(f"Invalid document id: {document_id!r}")
    return candidate


def get_temp_pdf_path(temp_id: str) -> Path:
    return Path(settings.temp_upload_path) / f"{temp_id}.pdf"


async def save_upload_stream(
    file: UploadFile,
    dest_path: Path,
    header: bytes,
    max_bytes: int,
) -> str:
    """
    Streams and writes file upload chunks to dest_path.
    Verifies maximum file size on the fly.
    Returns the SHA-256 hash of the fully written file content.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    sha256 = hashlib.sha256()
    sha256.update(header)

    total_bytes = len(header)

    exceeded = False
    async with aiofiles.open(dest_path, "wb") as f:
        await f.write(header)
        while True:
            # Read in chunks of 64KB
            chunk = await file.read(64 * 1024)
            if not chunk:
                break

            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                exceeded = True
                break

            sha256.update(chunk)
            await f.write(chunk)

    if exceeded:
        dest_path.unlink(missing_ok=True)
        raise FileOversizedError("File exceeds maximum allowed size")

    logger.info("Streamed and stored PDF", path=str(dest_path), bytes=total_bytes)
    return sha256.hexdigest()


def finalize_temp_pdf(temp_path: Path, document_id: str) -> str:
    """
    Moves temporary PDF file to its final persistent PVC location.
    """
    dest_path = get_pdf_path(document_id)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(temp_path), str(dest_path))
    logger.info("Finalized PDF path", document_id=document_id, path=str(dest_path))
    return str(dest_path)


def delete_pdf(document_id: str) -> None:
    path = get_pdf_path(document_id)
    if path.exists():
        path.unlink()
        logger.info("Deleted PDF", document_id=document_id)
