"""Unit tests for Module 10 Security Policy loading and enforcement."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.session.schemas import ConversationStateSchema, FactsSchema
from app.tools.exceptions import PolicyFileMissingError
from app.tools.policy import PolicyRegistry, SecurityPolicy
from app.tools.schemas import SecurityPolicySchema


class FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> None:
        return None


def _facts(**overrides: object) -> FactsSchema:
    return FactsSchema(tenant_id=uuid.uuid4(), session_id="s1", **overrides)


def _state(**overrides: object) -> ConversationStateSchema:
    return ConversationStateSchema(tenant_id=uuid.uuid4(), session_id="s1", **overrides)


def _policy(**overrides: object) -> SecurityPolicy:
    defaults: dict[str, object] = dict(
        tool_name="generate_quote",
        allowed_intents=["sales_inquiry", "quote_request"],
        required_state=["quote_slots_complete"],
        required_slots=["company", "product_interest", "quantity", "budget"],
        rate_limit="2/min",
        audit_log=True,
    )
    defaults.update(overrides)
    return SecurityPolicy(SecurityPolicySchema(**defaults))


@pytest.mark.asyncio
async def test_policy_check_denies_wrong_intent() -> None:
    policy = _policy()
    facts = _facts(company="Acme", product_interest="switch", quantity=5, budget=1000)

    result = await policy.check(
        intent="technical_support",
        state=_state(),
        facts=facts,
        tenant_id=uuid.uuid4(),
        session_id="s1",
        redis=FakeRedis(),
    )

    assert result.allowed is False
    assert result.clause_failed == "intent"


@pytest.mark.asyncio
async def test_policy_check_denies_missing_required_state() -> None:
    policy = _policy()
    facts = _facts()  # quote_slots_complete is False: no company/product_interest/quantity/budget

    result = await policy.check(
        intent="quote_request",
        state=_state(),
        facts=facts,
        tenant_id=uuid.uuid4(),
        session_id="s1",
        redis=FakeRedis(),
    )

    assert result.allowed is False
    assert result.clause_failed == "state"


@pytest.mark.asyncio
async def test_policy_check_denies_missing_required_slots() -> None:
    policy = _policy(required_state=[])
    facts = _facts(company="Acme", product_interest="switch")  # quantity/budget still missing

    result = await policy.check(
        intent="quote_request",
        state=_state(),
        facts=facts,
        tenant_id=uuid.uuid4(),
        session_id="s1",
        redis=FakeRedis(),
    )

    assert result.allowed is False
    assert result.clause_failed == "slots"


@pytest.mark.asyncio
async def test_policy_check_denies_over_rate_limit() -> None:
    policy = _policy(required_state=[], required_slots=[])
    facts = _facts()
    redis = FakeRedis()
    tenant_id = uuid.uuid4()

    first = await policy.check(
        intent="quote_request", state=_state(), facts=facts, tenant_id=tenant_id, session_id="s1", redis=redis
    )
    second = await policy.check(
        intent="quote_request", state=_state(), facts=facts, tenant_id=tenant_id, session_id="s1", redis=redis
    )
    third = await policy.check(
        intent="quote_request", state=_state(), facts=facts, tenant_id=tenant_id, session_id="s1", redis=redis
    )

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.clause_failed == "rate_limit"


@pytest.mark.asyncio
async def test_policy_check_allows_when_all_clauses_pass() -> None:
    policy = _policy()
    facts = _facts(company="Acme", product_interest="switch", quantity=5, budget=1000)

    result = await policy.check(
        intent="quote_request",
        state=_state(),
        facts=facts,
        tenant_id=uuid.uuid4(),
        session_id="s1",
        redis=FakeRedis(),
    )

    assert result.allowed is True
    assert result.clause_failed is None


def test_startup_fails_if_tool_missing_policy_file(tmp_path: Path) -> None:
    policy_dir = tmp_path / "policies"
    policy_dir.mkdir()
    (policy_dir / "respond.yaml").write_text(
        "tool_name: respond\nallowed_intents: [sales_inquiry]\nrequired_state: []\n"
        "required_slots: []\nrate_limit: null\naudit_log: false\n",
        encoding="utf-8",
    )
    registry = PolicyRegistry(str(policy_dir))
    registry.load()

    with pytest.raises(PolicyFileMissingError):
        registry.startup_self_check(["respond", "compare"])


def test_load_rejects_unknown_required_state_predicate(tmp_path: Path) -> None:
    policy_dir = tmp_path / "policies"
    policy_dir.mkdir()
    (policy_dir / "weird.yaml").write_text(
        "tool_name: weird\nallowed_intents: [sales_inquiry]\nrequired_state: [not_a_real_predicate]\n"
        "required_slots: []\nrate_limit: null\naudit_log: false\n",
        encoding="utf-8",
    )
    registry = PolicyRegistry(str(policy_dir))

    with pytest.raises(ValueError, match="not_a_real_predicate"):
        registry.load()


def test_load_raises_when_directory_missing(tmp_path: Path) -> None:
    registry = PolicyRegistry(str(tmp_path / "does-not-exist"))

    with pytest.raises(PolicyFileMissingError):
        registry.load()


def test_real_security_policies_satisfy_built_in_tools_self_check() -> None:
    """The repo's actual security_policies/ must cover the three built-in tools."""
    from app.dependencies import get_settings

    registry = PolicyRegistry(get_settings().tools.policy_directory)
    registry.load()

    registry.startup_self_check(["respond", "compare", "request_missing_slots"])
