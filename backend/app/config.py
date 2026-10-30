"""Application configuration with secret-safe diagnostics."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_values() -> dict[str, str]:
    values = {key: value for key, value in dotenv_values(PROJECT_ROOT / ".env").items() if value is not None}
    values.update({key: value for key, value in os.environ.items() if value is not None})
    return values


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    app_env: str
    app_name: str
    app_version: str
    mysql_dsn: str
    chroma_host: str
    chroma_port: int
    chroma_collection: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    embedding_base_url: str
    embedding_api_key: str
    embedding_model: str
    embedding_timeout_seconds: float
    embedding_batch_size: int
    embedding_max_retries: int
    embedding_rate_limit_per_second: float
    rerank_base_url: str
    rerank_api_key: str
    rerank_model: str
    auth_secret: str
    auth_secret_previous: str
    auth_token_issuer: str
    access_token_expire_minutes: int
    password_hash_iterations: int
    rag_upload_dir: str
    rag_max_file_size_bytes: int
    cors_origins: tuple[str, ...]
    service_timeout_seconds: float
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        values = _load_values()
        return cls(
            app_env=values.get("APP_ENV", "development"),
            app_name=values.get("APP_NAME", "chargeops"),
            app_version=values.get("APP_VERSION", "0.1.0"),
            mysql_dsn=values.get("MYSQL_DSN", ""),
            chroma_host=values.get("CHROMA_HOST", "127.0.0.1"),
            chroma_port=int(values.get("CHROMA_PORT", "8001")),
            chroma_collection=values.get("CHROMA_COLLECTION", "chargeops_documents"),
            llm_base_url=values.get("LLM_BASE_URL", "").rstrip("/"),
            llm_api_key=values.get("LLM_API_KEY", ""),
            llm_model=values.get("LLM_MODEL", ""),
            embedding_base_url=values.get("EMBEDDING_BASE_URL", "").rstrip("/"),
            embedding_api_key=values.get("EMBEDDING_API_KEY", ""),
            embedding_model=values.get("EMBEDDING_MODEL", ""),
            embedding_timeout_seconds=float(values.get("EMBEDDING_TIMEOUT_SECONDS", "180")),
            embedding_batch_size=int(values.get("EMBEDDING_BATCH_SIZE", "16")),
            embedding_max_retries=int(values.get("EMBEDDING_MAX_RETRIES", "3")),
            embedding_rate_limit_per_second=float(values.get("EMBEDDING_RATE_LIMIT_PER_SECOND", "0")),
            rerank_base_url=values.get("RERANK_BASE_URL", "").rstrip("/"),
            rerank_api_key=values.get("RERANK_API_KEY", ""),
            rerank_model=values.get("RERANK_MODEL", ""),
            auth_secret=values.get("AUTH_SECRET", ""),
            auth_secret_previous=values.get("AUTH_SECRET_PREVIOUS", ""),
            auth_token_issuer=values.get("AUTH_TOKEN_ISSUER", "chargeops"),
            access_token_expire_minutes=int(values.get("ACCESS_TOKEN_EXPIRE_MINUTES", "60")),
            password_hash_iterations=int(values.get("PASSWORD_HASH_ITERATIONS", "310000")),
            rag_upload_dir=values.get("RAG_UPLOAD_DIR", "data/raw/user_upload/rag"),
            rag_max_file_size_bytes=int(values.get("RAG_MAX_FILE_SIZE_MB", "5")) * 1024 * 1024,
            cors_origins=_csv(values.get("CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173")),
            service_timeout_seconds=float(values.get("READY_TIMEOUT_SECONDS", "5")),
            log_level=values.get("LOG_LEVEL", "INFO").upper(),
        )

    def validate(self) -> None:
        if not self.mysql_dsn:
            raise ValueError("MYSQL_DSN is required")
        if self.app_env.lower() == "production" and self.auth_secret in {"", "replace-with-a-random-long-secret"}:
            raise ValueError("AUTH_SECRET must be configured in production")
        if self.chroma_port <= 0:
            raise ValueError("CHROMA_PORT must be a positive integer")
        if self.access_token_expire_minutes <= 0:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be positive")
        if self.password_hash_iterations < 100_000:
            raise ValueError("PASSWORD_HASH_ITERATIONS must be at least 100000")
        if self.rag_max_file_size_bytes <= 0:
            raise ValueError("RAG_MAX_FILE_SIZE_MB must be positive")
        if self.embedding_timeout_seconds <= 0:
            raise ValueError("EMBEDDING_TIMEOUT_SECONDS must be positive")
        if self.embedding_batch_size <= 0:
            raise ValueError("EMBEDDING_BATCH_SIZE must be positive")
        if self.embedding_max_retries < 0:
            raise ValueError("EMBEDDING_MAX_RETRIES cannot be negative")
        if self.embedding_rate_limit_per_second < 0:
            raise ValueError("EMBEDDING_RATE_LIMIT_PER_SECOND cannot be negative")

    def public_summary(self) -> dict[str, object]:
        """Return diagnostics without secrets or credential values."""
        return {
            "app_env": self.app_env,
            "app_name": self.app_name,
            "app_version": self.app_version,
            "chroma": {"host": self.chroma_host, "port": self.chroma_port, "collection": self.chroma_collection},
            "llm": {"configured": bool(self.llm_base_url and self.llm_api_key and self.llm_model), "model": self.llm_model or None},
            "embedding": {"configured": bool(self.embedding_base_url and self.embedding_api_key and self.embedding_model), "model": self.embedding_model or None},
            "rerank": {"configured": bool(self.rerank_base_url and self.rerank_api_key and self.rerank_model), "model": self.rerank_model or None},
            "auth": {"token_issuer": self.auth_token_issuer, "access_token_expire_minutes": self.access_token_expire_minutes},
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings.from_env()
    settings.validate()
    return settings
