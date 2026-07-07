"""Security Policy loading (YAML, at startup) and per-call enforcement."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import yaml
from redis.asyncio import Redis

from app.dependencies import get_settings
from app.logging_config import get_logger
from app.quotes.schemas import quote_slots_complete
from app.session.schemas import ConversationStateSchema, FactsSchema
from app.tools.exceptions import PolicyFileMissingError
from app.tools.schemas import PolicyCheckResult, SecurityPolicySchema

logger = get_logger(__name__)

_RATE_LIMIT_PATTERN = re.compile(r"^(\d+)/(sec|min|hour)$")
_WINDOW_SECONDS: dict[str, int] = {"sec": 1, "min": 60, "hour": 3600}


def contact_info_complete(facts: FactsSchema, state: ConversationStateSchema) -> bool:
    """Return whether at least one contact method has been captured."""
    return facts.contact_email is not None or facts.contact_phone is not None


# Single source of truth for `required_state` predicate names used in policy YAML.
# Unknown names here fail startup (see PolicyRegistry.load).
PREDICATE_REGISTRY: dict[str, Callable[[FactsSchema, ConversationStateSchema], bool]] = {
    "quote_slots_complete": quote_slots_complete,
    "contact_info_complete": contact_info_complete,
}


def _parse_rate_limit(rate_limit: str) -> tuple[int, int]:
    """Parse a "N/unit" string into (limit, window_seconds)."""
    match = _RATE_LIMIT_PATTERN.match(rate_limit)
    if match is None:
        raise ValueError(f"Invalid rate_limit format: {rate_limit!r}")
    return int(match.group(1)), _WINDOW_SECONDS[match.group(2)]


class SecurityPolicy:
    """One tool's parsed policy, plus the runtime `.check(...)` enforcement."""

    def __init__(self, schema: SecurityPolicySchema) -> None:
        self.schema = schema

    @property
    def tool_name(self) -> str:
        return self.schema.tool_name

    @property
    def audit_log(self) -> bool:
        return self.schema.audit_log

    async def check(
        self,
        *,
        intent: str,
        state: ConversationStateSchema,
        facts: FactsSchema,
        tenant_id: UUID,
        session_id: str,
        redis: Redis,
    ) -> PolicyCheckResult:
        """Check intent, then required state predicates, then slots, then rate limit."""
        if intent not in self.schema.allowed_intents:
            return PolicyCheckResult(
                allowed=False,
                reason=f"intent {intent!r} not in allowed_intents",
                clause_failed="intent",
            )

        for predicate_name in self.schema.required_state:
            predicate = PREDICATE_REGISTRY[predicate_name]
            if not predicate(facts, state):
                return PolicyCheckResult(
                    allowed=False,
                    reason=f"required_state predicate {predicate_name!r} failed",
                    clause_failed="state",
                )

        for slot in self.schema.required_slots:
            if getattr(facts, slot, None) is None:
                return PolicyCheckResult(
                    allowed=False,
                    reason=f"required slot {slot!r} is missing",
                    clause_failed="slots",
                )

        if self.schema.rate_limit is not None:
            within_limit = await self._check_rate_limit(tenant_id, session_id, redis)
            if not within_limit:
                return PolicyCheckResult(
                    allowed=False,
                    reason=f"rate limit {self.schema.rate_limit!r} exceeded",
                    clause_failed="rate_limit",
                )

        return PolicyCheckResult(allowed=True)

    async def _check_rate_limit(self, tenant_id: UUID, session_id: str, redis: Redis) -> bool:
        assert self.schema.rate_limit is not None
        limit, window_seconds = _parse_rate_limit(self.schema.rate_limit)
        key = f"rate_limit:tool:{tenant_id}:{session_id}:{self.schema.tool_name}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window_seconds)
        return count <= limit


class PolicyRegistry:
    """Loads all YAML security policy files into `dict[str, SecurityPolicy]` at startup."""

    def __init__(self, policy_directory: str) -> None:
        self.policy_directory = Path(policy_directory).resolve()
        self._policies: dict[str, SecurityPolicy] = {}

    def load(self) -> None:
        """Parse every `*.yaml` file, validating required_state predicates eagerly."""
        self._policies = {}
        if not self.policy_directory.is_dir():
            raise PolicyFileMissingError(f"Security policy directory not found: {self.policy_directory}")

        for path in sorted(self.policy_directory.glob("*.yaml")):
            with path.open("r", encoding="utf-8") as handle:
                raw = yaml.safe_load(handle)
            schema = SecurityPolicySchema(**raw)
            for predicate_name in schema.required_state:
                if predicate_name not in PREDICATE_REGISTRY:
                    raise ValueError(f"Unknown required_state predicate {predicate_name!r} in {path}")
            self._policies[schema.tool_name] = SecurityPolicy(schema)

        logger.debug("security_policies_loaded", extra={"count": len(self._policies)})

    def get(self, tool_name: str) -> SecurityPolicy | None:
        """Return the loaded policy for a tool, or None if it has never been loaded."""
        return self._policies.get(tool_name)

    def startup_self_check(self, registered_tool_names: list[str]) -> None:
        """Fail fast if any registered tool has no corresponding policy file."""
        missing = [name for name in registered_tool_names if name not in self._policies]
        if missing:
            raise PolicyFileMissingError(f"No security policy file for tools: {missing}")


# Single module-level singleton — callers import `policy_registry`, they do not
# instantiate PolicyRegistry themselves.
policy_registry = PolicyRegistry(get_settings().tools.policy_directory)
