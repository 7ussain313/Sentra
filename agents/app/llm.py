"""Thin LLM wrapper. The loop depends on `LLM`, not on a provider SDK, so tests
can script the model and a provider outage is a single, catchable error."""
import json
import time
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


class OpenAICompatLLM:
    """Any OpenAI-compatible chat endpoint (Gemini free tier, Groq, Ollama, ...).

    The loop's transcript stays in Messages-API shape; this class translates it to
    chat-completions messages and back, so nothing above `LLM` changes."""

    def __init__(self) -> None:
        cfg = get_settings()
        if not cfg.llm_api_key:
            raise LLMUnavailable("LLM_API_KEY is not configured")
        import httpx

        self._httpx = httpx
        self._url = cfg.llm_base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {cfg.llm_api_key}"}
        self._model = cfg.llm_model

    @staticmethod
    def _convert(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            content = m["content"]
            if isinstance(content, str):
                out.append({"role": m["role"], "content": content})
                continue
            text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            if m["role"] == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": text or None}
                calls = []
                for b in content:
                    if b.get("type") != "tool_use":
                        continue
                    call = {"id": b["id"], "type": "function",
                            "function": {"name": b["name"], "arguments": json.dumps(b["input"])}}
                    if b.get("extra_content"):  # Gemini 3 thought signature must be echoed back
                        call["extra_content"] = b["extra_content"]
                    calls.append(call)
                if calls:
                    msg["tool_calls"] = calls
                out.append(msg)
                continue
            for b in content:
                if b.get("type") == "tool_result":
                    c = b.get("content", "")
                    if not isinstance(c, str):
                        c = "".join(x.get("text", "") for x in c)
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": c})
            if text:
                out.append({"role": "user", "content": text})
        return out

    def complete(self, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]] | None = None, max_tokens: int = 2048) -> LLMReply:
        body: dict[str, Any] = {"model": self._model, "max_tokens": max_tokens,
                                "messages": self._convert(system, messages)}
        if tools:
            body["tools"] = [{"type": "function", "function": {
                "name": t["name"], "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}})}}
                for t in tools]
        try:
            for attempt in range(4):  # free tiers shed load with 429/503; back off and retry
                try:
                    r = self._httpx.post(self._url, json=body, headers=self._headers, timeout=180)
                except self._httpx.TimeoutException:
                    if attempt == 3:
                        raise
                    time.sleep(2 ** attempt * 3)
                    continue
                if r.status_code not in (429, 500, 502, 503, 504) or attempt == 3:
                    break
                time.sleep(2 ** attempt * 3)
            r.raise_for_status()
            choice = r.json()["choices"][0]
        except (self._httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            raise LLMUnavailable(f"{type(e).__name__}: {e}") from e
        msg = choice["message"]
        reply = LLMReply(stop_reason="tool_use" if msg.get("tool_calls") else "end_turn")
        if msg.get("content"):
            reply.text = msg["content"]
            reply.blocks.append({"type": "text", "text": msg["content"]})
        for i, tc in enumerate(msg.get("tool_calls") or []):
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except ValueError:
                args = {}
            call_id = tc.get("id") or f"call_{i}"
            name = tc["function"]["name"]
            reply.tool_calls.append(ToolCall(call_id, name, args))
            block = {"type": "tool_use", "id": call_id, "name": name, "input": args}
            if tc.get("extra_content"):
                block["extra_content"] = tc["extra_content"]
            reply.blocks.append(block)
        return reply


def default_llm() -> LLM:
    if get_settings().llm_provider == "openai_compat":
        return OpenAICompatLLM()
    return AnthropicLLM()
