"""Observability package."""

from __future__ import annotations

from app.observability.registry import MetricsRegistry, metrics_registry

__all__ = ["MetricsRegistry", "metrics_registry"]
