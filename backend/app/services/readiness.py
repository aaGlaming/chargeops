"""Dependency checks used by the readiness endpoint."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import text

from app.config import Settings
from app.db import get_engine


def _check(name: str, status: str, detail: str, retryable: bool = False) -> dict[str, Any]:
    return {"service": name, "status": status, "detail": detail, "retryable": retryable}


def check_mysql(settings: Settings) -> dict[str, Any]:
    try:
        with get_engine(settings.mysql_dsn).connect() as connection:
            connection.execute(text("SELECT 1"))
        return _check("mysql", "ok", "database connection available")
    except Exception as exc:
        return _check("mysql", "down", exc.__class__.__name__, True)


def check_http_service(settings: Settings, name: str, base_url: str, api_key: str, model: str) -> dict[str, Any]:
    if not base_url or not api_key or not model:
        return _check(name, "not_configured", "endpoint, API key or model is missing")
    try:
        with httpx.Client(timeout=settings.service_timeout_seconds) as client:
            response = client.get(f"{base_url}/models", headers={"Authorization": f"Bearer {api_key}"})
        if response.status_code == 200:
            return _check(name, "ok", f"models endpoint available; model={model}")
        return _check(name, "down", f"models endpoint returned HTTP {response.status_code}", True)
    except Exception as exc:
        return _check(name, "down", exc.__class__.__name__, True)


def check_chroma(settings: Settings) -> dict[str, Any]:
    for version in ("v2", "v1"):
        try:
            with httpx.Client(timeout=settings.service_timeout_seconds) as client:
                response = client.get(f"http://{settings.chroma_host}:{settings.chroma_port}/api/{version}/heartbeat")
            if response.status_code == 200:
                return _check("chroma", "ok", f"/api/{version}/heartbeat available")
        except Exception:
            continue
    return _check("chroma", "down", "heartbeat unavailable", True)


def readiness_report(settings: Settings) -> dict[str, Any]:
    checks = [
        check_mysql(settings),
        check_chroma(settings),
        check_http_service(settings, "chat", settings.llm_base_url, settings.llm_api_key, settings.llm_model),
        check_http_service(settings, "embedding", settings.embedding_base_url, settings.embedding_api_key, settings.embedding_model),
    ]
    if settings.rerank_base_url or settings.rerank_api_key or settings.rerank_model:
        checks.append(check_http_service(settings, "rerank", settings.rerank_base_url, settings.rerank_api_key, settings.rerank_model))
    ready = all(check["status"] == "ok" for check in checks if check["service"] in {"mysql", "chroma", "chat", "embedding"})
    return {"status": "ok" if ready else "degraded", "ready": ready, "checks": checks}
