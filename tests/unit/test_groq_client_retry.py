"""Regression tests for GroqClient's bounded 429 retry.

Real-world context: Groq's free tier rate-limits per-second/per-minute windows
that a single chat turn's 2-4 LLM calls (facts extraction, classification,
respond, translation) can burst through in normal use, not just heavy manual
testing. Before this fix, a single 429 immediately failed the call, which
cascaded into stale facts, wrong intent classification, or the generic
"I could not complete that request" fallback leaking to the user for what is
often a sub-second blip.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.llm.groq_client import GroqClient


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        groq=SimpleNamespace(
            api_key=SimpleNamespace(get_secret_value=lambda: "test-key"),
            base_url="https://api.groq.test/openai/v1",
            model="llama-3.3-70b-versatile",
            timeout_seconds=5,
        ),
    )


class FakeResponse:
    def __init__(self, status_code: int, json_body: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self._json_body = json_body
        self.headers = headers or {}
        self._request = httpx.Request("POST", "https://api.groq.test/openai/v1/chat/completions")

    def json(self) -> dict[str, Any]:
        return self._json_body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status {self.status_code}", request=self._request,
                response=httpx.Response(self.status_code, request=self._request),
            )


class FakeHttpClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def post(self, *args: Any, **kwargs: Any) -> FakeResponse:
        response = self._responses[self.calls]
        self.calls += 1
        return response


@pytest.mark.asyncio
async def test_post_retries_once_after_a_single_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GroqClient(_settings())
    fake_http = FakeHttpClient(
        [
            FakeResponse(429, {}),
            FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]}),
        ]
    )
    monkeypatch.setattr("app.llm.groq_client.get_shared_http_client", lambda settings: fake_http)

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.llm.groq_client.asyncio.sleep", fake_sleep)

    result = await client._post({"model": "x"})

    assert result == {"choices": [{"message": {"content": "ok"}}]}
    assert fake_http.calls == 2
    assert len(sleep_calls) == 1


@pytest.mark.asyncio
async def test_post_gives_up_after_exhausting_retries_on_persistent_429(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GroqClient(_settings())
    fake_http = FakeHttpClient([FakeResponse(429, {}) for _ in range(5)])
    monkeypatch.setattr("app.llm.groq_client.get_shared_http_client", lambda settings: fake_http)
    monkeypatch.setattr("app.llm.groq_client.asyncio.sleep", lambda seconds: _noop())

    with pytest.raises(httpx.HTTPStatusError):
        await client._post({"model": "x"})

    assert fake_http.calls == 3  # initial attempt + 2 retries, per _MAX_429_RETRIES


async def _noop() -> None:
    return None


@pytest.mark.asyncio
async def test_post_does_not_retry_non_429_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GroqClient(_settings())
    fake_http = FakeHttpClient([FakeResponse(500, {})])
    monkeypatch.setattr("app.llm.groq_client.get_shared_http_client", lambda settings: fake_http)

    with pytest.raises(httpx.HTTPStatusError):
        await client._post({"model": "x"})

    assert fake_http.calls == 1
