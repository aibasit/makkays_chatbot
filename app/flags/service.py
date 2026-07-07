"""FeatureFlagsService — merges env defaults with DB overrides, TTL-cached per tenant."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from cachetools import TTLCache
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.flags.repository import FeatureFlagsRepository
from app.flags.schemas import FORCED_DISABLED_FLAGS, VALID_FLAG_NAMES, FeatureFlags
from app.logging_config import get_logger

logger = get_logger(__name__)

_VALID_BOOL_STRINGS: dict[str, bool] = {"true": True, "false": False, "1": True, "0": False}


def _coerce_bool(flag_name: str, value: Any) -> bool | None:
    """Return a proper bool, or None (logging a warning) if the value is unusable."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in _VALID_BOOL_STRINGS:
        return _VALID_BOOL_STRINGS[value.strip().lower()]
    logger.warning(
        "feature_flags_invalid_value_ignored",
        extra={"flag_name": flag_name, "value": value},
    )
    return None


class FeatureFlagsService:
    """Resolves a per-turn FeatureFlags snapshot: env defaults + DB overrides, TTL-cached."""

    def __init__(self, db_session: AsyncSession, settings: Settings) -> None:
        self.repository = FeatureFlagsRepository(db_session)
        self.settings = settings
        self._cache: TTLCache = TTLCache(maxsize=10, ttl=60)

    async def resolve(self, tenant_id: UUID) -> FeatureFlags:
        """Return the resolved FeatureFlags snapshot for one tenant (cached up to 60s)."""
        cached = self._cache.get(tenant_id)
        if cached is not None:
            return cached

        merged: dict[str, Any] = self.settings.flags.model_dump()

        try:
            overrides = await self.repository.get_all(tenant_id)
        except ProgrammingError as exc:
            logger.warning("feature_flags_table_absent_using_env_defaults", extra={"error": str(exc)})
            overrides = {}
        except Exception as exc:
            logger.warning("feature_flags_db_unreachable_using_env_defaults", extra={"error": str(exc)})
            overrides = {}

        for flag_name, raw_value in overrides.items():
            if flag_name not in VALID_FLAG_NAMES:
                logger.warning("feature_flags_unrecognized_flag_ignored", extra={"flag_name": flag_name})
                continue
            value = _coerce_bool(flag_name, raw_value)
            if value is None:
                continue
            merged[flag_name] = value

        for flag_name in FORCED_DISABLED_FLAGS:
            merged[flag_name] = False

        flags = FeatureFlags(**merged)
        logger.debug("feature_flags_resolved", extra={"tenant_id": str(tenant_id), "flags": merged})
        self._cache[tenant_id] = flags
        return flags
