"""Thin LLM wrapper. The loop depends on `LLM`, not on a provider SDK, so tests
can script the model and a provider outage is a single, catchable error."""
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.config import get_settings


class LLMUnavailable(Exception):
    """The model could not be reached or is not configured."""


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMReply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    # Assistant content blocks in Messages-API shape, appended to the transcript as-is.
    blocks: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = "end_turn"


class LLM(Protocol):
    def complete(self, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]] | None = None, max_tokens: int = 2048) -> LLMReply: ...


class AnthropicLLM:
    def __init__(self) -> None:
        cfg = get_settings()
        if not cfg.anthropic_api_key:
            raise LLMUnavailable("ANTHROPIC_API_KEY is not configured")
        import anthropic  # imported lazily so tests and the UI never need the SDK

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=cfg.anthropic_api_key, max_retries=2, timeout=60)
        self._model = cfg.llm_model

    def complete(self, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]] | None = None, max_tokens: int = 2048) -> LLMReply:
        kwargs: dict[str, Any] = {
            "model": self._model, "max_tokens": max_tokens, "system": system, "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        try:
            resp = self._client.messages.create(**kwargs)
        except self._anthropic.APIError as e:
            raise LLMUnavailable(f"{type(e).__name__}: {e}") from e
        reply = LLMReply(stop_reason=resp.stop_reason or "end_turn")
        for block in resp.content:
            if block.type == "text":
                reply.text += block.text
                reply.blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                reply.tool_calls.append(ToolCall(block.id, block.name, dict(block.input)))
                reply.blocks.append({"type": "tool_use", "id": block.id,
                                     "name": block.name, "input": dict(block.input)})
        return reply


def default_llm() -> LLM:
    return AnthropicLLM()
