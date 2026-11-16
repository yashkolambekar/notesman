from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Embeddings (Google AI Studio)
    gemini_api_key: str = ""
    embed_model: str = "gemini-embedding-2"
    embed_dim: int = 1536
    embed_batch_size: int = 16  # small batches keep each request under the token-per-minute limit

    # Chat (OpenRouter)
    openrouter_api_key: str = ""
    chat_model: str = "anthropic/claude-sonnet-5.5"
    # Cheaper model for query rewriting, reranking and the grounding check. Empty = use CHAT_MODEL.
    fast_model: str = ""
    grounding_check: bool = True
    default_marks: int = 5  # Mumbai University style: a 5-mark answer fills one page

    # Postgres
    database_url: str = "postgresql+asyncpg://notesman:notesman@localhost:5432/notesman"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "notesman_chunks"

    # Google sign-in (OAuth)
    google_auth_client_id: str = ""
    google_auth_client_secret: str = ""

    # Cloudflare R2 (S3 API): original uploads and extracted text
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""

    # Sessions and roles
    session_secret: str = ""
    public_base_url: str = "http://localhost:3000"
    superadmin_email: str = ""


    @field_validator("database_url")
    @classmethod
    def _asyncpg_url(cls, v: str) -> str:
        """Accept the URL as hosts hand it out (postgres://, postgresql://, ?sslmode=) and turn it
        into what SQLAlchemy + asyncpg need."""
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                v = "postgresql+asyncpg://" + v[len(prefix) :]
        return v.replace("sslmode=", "ssl=")


@lru_cache
def get_settings() -> Settings:
    return Settings()
