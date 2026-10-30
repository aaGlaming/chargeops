"""Process-local request and operation telemetry used by the monitoring API."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Any


@dataclass(frozen=True)
class TelemetrySample:
    component: str
    duration_ms: float
    status: str


_lock = Lock()
_samples: deque[TelemetrySample] = deque(maxlen=5000)


def record_sample(component: str, duration_ms: float, status: str = "success") -> None:
    with _lock:
        _samples.append(TelemetrySample(component=component, duration_ms=round(max(duration_ms, 0), 2), status=status))


def snapshot() -> dict[str, Any]:
    with _lock:
        samples = list(_samples)
    requests = [item for item in samples if item.component == "http_request"]
    errors = [item for item in requests if item.status == "error"]
    durations = sorted(item.duration_ms for item in requests)
    index = min(len(durations) - 1, max(0, int(len(durations) * 0.95))) if durations else 0
    components: dict[str, dict[str, Any]] = {}
    for item in samples:
        current = components.setdefault(item.component, {"count": 0, "error_count": 0, "durations_ms": []})
        current["count"] += 1
        current["error_count"] += int(item.status == "error")
        current["durations_ms"].append(item.duration_ms)
    for value in components.values():
        values = sorted(value.pop("durations_ms"))
        value["p95_latency_ms"] = values[min(len(values) - 1, max(0, int(len(values) * 0.95)))] if values else 0
    return {
        "window": "process_lifetime_max_5000_samples",
        "request_count": len(requests),
        "error_count": len(errors),
        "error_rate": round(len(errors) / len(requests), 4) if requests else 0,
        "p95_latency_ms": durations[index] if durations else 0,
        "components": components,
    }
