"""Message translation of the OpenAI-compatible adapter (Messages-API transcript <-> chat completions)."""
import json

from app.llm import OpenAICompatLLM

convert = OpenAICompatLLM._convert


def test_plain_text_and_system():
    out = convert("sys", [{"role": "user", "content": "hi"}])
    assert out == [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]


def test_tool_round_trip_keeps_ids_and_signature():
    sig = {"google": {"thought_signature": "abc"}}
    msgs = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "checking"},
            {"type": "tool_use", "id": "c1", "name": "read_logs", "input": {"service": "odoo"},
             "extra_content": sig},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "c1", "content": "ok: 3 lines"},
        ]},
    ]
    out = convert("sys", msgs)
    assistant = out[2]
    assert assistant["role"] == "assistant" and assistant["content"] == "checking"
    call = assistant["tool_calls"][0]
    assert call["id"] == "c1" and call["extra_content"] == sig
    assert json.loads(call["function"]["arguments"]) == {"service": "odoo"}
    assert out[3] == {"role": "tool", "tool_call_id": "c1", "content": "ok: 3 lines"}


def test_tool_result_with_block_content_is_flattened():
    msgs = [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "c9", "content": [{"type": "text", "text": "a"},
                                                                  {"type": "text", "text": "b"}]},
    ]}]
    assert convert("s", msgs)[1] == {"role": "tool", "tool_call_id": "c9", "content": "ab"}
