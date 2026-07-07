"""Orchestrator.on_turn is intentionally deferred until Modules 08-10, 13, and 16 exist.

This test documents that current state so a future implementer's change to
`Orchestrator.on_turn` is a deliberate decision, not an accidental regression.
"""

from __future__ import annotations

import uuid

import pytest

from app.orchestrator.orchestrator import Orchestrator


@pytest.mark.asyncio
async def test_on_turn_raises_until_downstream_modules_exist() -> None:
    orchestrator = Orchestrator()

    with pytest.raises(NotImplementedError, match="Modules 08"):
        await orchestrator.on_turn(uuid.uuid4(), "s1", "hello", llm_client=None, prompt_provider=None)  # type: ignore[arg-type]
