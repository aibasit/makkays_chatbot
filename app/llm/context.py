"""Canonical context builder for all LLM callers."""

from __future__ import annotations

import json
from typing import Any

from app.llm.schemas import ChatMessage, ContextBuildMetadata


def build_llm_messages(
    system_prompt: str,
    facts: Any | None = None,
    state: Any | None = None,
    recent_turns: list[Any] | None = None,
    tool_results: list[Any] | None = None,
    planner_metadata: dict[str, Any] | None = None,
    retrieved_sources: list[dict[str, Any]] | None = None,
    quote_summary: dict[str, Any] | None = None,
    latest_user_message: str | None = None,
    max_context_chars: int = 24000,
) -> tuple[list[ChatMessage], ContextBuildMetadata]:
    """Build canonical LLM messages and context metadata.

    The first and only system message is always `system_prompt`. Additional context is
    represented as regular user/tool messages so downstream validation sees exactly one
    leading system message.
    """
    if not system_prompt.strip():
        raise ValueError("system_prompt is required")
    if max_context_chars <= 0:
        raise ValueError("max_context_chars must be positive")

    messages = [ChatMessage(role="system", content=system_prompt)]
    metadata = ContextBuildMetadata(prompt_refs=_prompt_refs(planner_metadata))
    used_chars = len(system_prompt)

    context_block = _build_context_block(
        facts=facts,
        state=state,
        planner_metadata=planner_metadata,
        quote_summary=quote_summary,
    )
    used_chars = _append_if_fits(
        messages,
        ChatMessage(role="user", content=context_block),
        used_chars,
        max_context_chars,
    )

    source_messages, included_source_ids, truncated_sources = _source_messages(
        retrieved_sources or [],
        used_chars,
        max_context_chars,
    )
    messages.extend(source_messages)
    used_chars += sum(len(message.content) for message in source_messages)
    metadata.included_source_ids = included_source_ids
    metadata.truncated_source_count = truncated_sources

    turn_messages, included_turn_count, truncated_turn_count = _recent_turn_messages(
        recent_turns or [],
        used_chars,
        max_context_chars,
    )
    messages.extend(turn_messages)
    used_chars += sum(len(message.content) for message in turn_messages)
    metadata.included_turn_count = included_turn_count
    metadata.truncated_turn_count = truncated_turn_count

    for result in tool_results or []:
        tool_message = _tool_result_message(result)
        if tool_message is not None:
            used_chars = _append_if_fits(messages, tool_message, used_chars, max_context_chars)

    if latest_user_message:
        latest = ChatMessage(role="user", content=latest_user_message)
        _append_with_tail_truncation(messages, latest, used_chars, max_context_chars)

    return messages, metadata


def _append_if_fits(
    messages: list[ChatMessage],
    message: ChatMessage,
    used_chars: int,
    max_context_chars: int,
) -> int:
    if not message.content:
        return used_chars
    if used_chars + len(message.content) > max_context_chars:
        return used_chars
    messages.append(message)
    return used_chars + len(message.content)


def _append_with_tail_truncation(
    messages: list[ChatMessage],
    message: ChatMessage,
    used_chars: int,
    max_context_chars: int,
) -> None:
    remaining = max_context_chars - used_chars
    if remaining <= 0:
        return
    content = message.content[-remaining:] if len(message.content) > remaining else message.content
    messages.append(
        ChatMessage(role=message.role, content=content, tool_call_id=message.tool_call_id)
    )


def _build_context_block(
    *,
    facts: Any | None,
    state: Any | None,
    planner_metadata: dict[str, Any] | None,
    quote_summary: dict[str, Any] | None,
) -> str:
    payload: dict[str, Any] = {}
    if facts is not None:
        payload["facts"] = _model_or_value(facts)
    if state is not None:
        payload["conversation_state"] = _model_or_value(state)
    if planner_metadata is not None:
        payload["planner_metadata"] = planner_metadata
    if quote_summary is not None:
        payload["quote_summary"] = quote_summary
    if not payload:
        return ""
    return "Context:\n" + json.dumps(payload, default=str, separators=(",", ":"))


def _source_messages(
    sources: list[dict[str, Any]],
    used_chars: int,
    max_context_chars: int,
) -> tuple[list[ChatMessage], list[str], int]:
    messages: list[ChatMessage] = []
    included_ids: list[str] = []
    truncated = 0
    current_chars = used_chars
    for source in sources:
        source_id = str(source.get("id") or source.get("source_id") or len(included_ids) + 1)
        content = json.dumps(source, default=str, separators=(",", ":"))
        message = ChatMessage(role="user", content=f"Retrieved source {source_id}:\n{content}")
        if current_chars + len(message.content) > max_context_chars:
            truncated += 1
            continue
        messages.append(message)
        included_ids.append(source_id)
        current_chars += len(message.content)
    return messages, included_ids, truncated


def _recent_turn_messages(
    turns: list[Any],
    used_chars: int,
    max_context_chars: int,
) -> tuple[list[ChatMessage], int, int]:
    messages: list[ChatMessage] = []
    current_chars = used_chars
    included = 0
    truncated = 0
    for turn in turns:
        user_message = getattr(turn, "user_message", None)
        assistant_message = getattr(turn, "assistant_message", None)
        candidate_messages = []
        if user_message:
            candidate_messages.append(ChatMessage(role="user", content=str(user_message)))
        if assistant_message:
            candidate_messages.append(ChatMessage(role="assistant", content=str(assistant_message)))
        candidate_length = sum(len(message.content) for message in candidate_messages)
        if current_chars + candidate_length > max_context_chars:
            truncated += 1
            continue
        messages.extend(candidate_messages)
        current_chars += candidate_length
        included += 1
    return messages, included, truncated


def _tool_result_message(result: Any) -> ChatMessage | None:
    role = getattr(result, "role", None) or (
        result.get("role") if isinstance(result, dict) else None
    )
    content = getattr(result, "content", None) or (
        result.get("content") if isinstance(result, dict) else None
    )
    tool_call_id = getattr(result, "tool_call_id", None) or (
        result.get("tool_call_id") if isinstance(result, dict) else None
    )
    if role != "tool" or content is None or tool_call_id is None:
        return None
    return ChatMessage(role="tool", content=str(content), tool_call_id=str(tool_call_id))


def _model_or_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _prompt_refs(planner_metadata: dict[str, Any] | None) -> dict[str, str]:
    if not planner_metadata:
        return {}
    refs = planner_metadata.get("prompt_refs")
    if not isinstance(refs, dict):
        return {}
    return {str(key): str(value) for key, value in refs.items()}
