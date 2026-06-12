import tempfile
from pathlib import Path
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_DIR = Path(__file__).resolve().parents[2]
_BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_ROOT_DIR / ".env", _BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    korca_env: str = "development"
    korca_debug: bool = False
    korca_log_level: str = "INFO"
    korca_auth_password: str = ""
    korca_auth_cookie_secret: str = ""
    korca_auth_cookie_secret_file: str = ""
    korca_auth_cookie_secure: bool = False
    cors_allowed_origins: list[str] | str = ["http://localhost:5173", "http://localhost:3000"]

    @field_validator(
        "cors_allowed_origins",
        "teamwork_subject_blocklist",
        "teamwork_personal_domains",
        mode="before",
    )
    @classmethod
    def _parse_str_list(cls, v: Any) -> list[str] | Any:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            if v.startswith("[") and v.endswith("]"):
                import json

                try:
                    return json.loads(v)
                except json.JSONDecodeError:
                    pass
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    # Gemini document processing, generation, and embeddings
    gemini_api_key: str = ""
    gemini_embedding_model: str = "models/gemini-embedding-001"
    gemini_generation_model: str = "gemini-2.5-flash"

    # Teamwork Desk
    teamwork_api_key: str = ""
    teamwork_subdomain: str = ""
    teamwork_fallback_agent_email: str = ""
    teamwork_staging_expert_email: str = ""
    teamwork_staging_expert_name: str = ""
    teamwork_subject_blocklist: list[str] | str = []
    teamwork_personal_domains: list[str] | str = []

    # Neo4j Aura DB
    neo4j_uri_aura: str = ""
    neo4j_user_aura: str = ""
    neo4j_pass_aura: str = ""
    neo4j_database_aura: str = ""

    # Aura Agent
    aura_client_id: str = ""
    aura_client_secret: str = ""
    aura_agent_endpoint: str = ""

    # Aura routing trace/debug store
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = ""
    aura_trace_enabled: bool = False
    aura_trace_sample_rate: float = 1.0

    # Redis
    redis_url: str = "redis://localhost:6379"

    # File storage
    upload_max_size_mb: int = 50
    temp_upload_path: str = str(Path(tempfile.gettempdir()) / "korca-uploads")
    pdf_storage_path: str = "/data/pdfs"
    backup_storage_path: str = "/data/pdfs/backups"


settings = Settings()
