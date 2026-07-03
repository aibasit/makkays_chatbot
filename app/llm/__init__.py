"""LLM engine public interface."""

from app.llm.client import OllamaClient, close_shared_http_client
from app.llm.context import build_llm_messages
from app.llm.exceptions import LLMMalformedOutputError, LLMTimeoutError, LLMUnavailableError
from app.llm.schemas import (
    ChatMessage,
    ContextBuildMetadata,
    LLMClientProtocol,
    LLMResponse,
    StructuredOutputRequest,
    ToolCall,
    ToolResult,
)
from app.llm.tool_schema import build_tool_schema

__all__ = [
    "ChatMessage",
    "ContextBuildMetadata",
    "LLMClientProtocol",
    "LLMMalformedOutputError",
    "LLMResponse",
    "LLMTimeoutError",
    "LLMUnavailableError",
    "OllamaClient",
    "StructuredOutputRequest",
    "ToolCall",
    "ToolResult",
    "build_llm_messages",
    "build_tool_schema",
    "close_shared_http_client",
]
