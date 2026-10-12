"""The reasoning loop shared by the agents.

    for step in 1..max_steps:
        reply = llm(messages, tools)
        no tool calls -> final answer
        each tool call is validated and run; action tools wait for human approval

Stop conditions: final answer, step limit, an action rejected or timed out, an
LLM failure that cannot be retried. Safety is enforced by the tool registry
(allowlists, validation, approval gate), not by the prompt.
"""
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from app import approvals as approvals_mod
from app import tools
from app.llm import LLM, LLMUnavailable
from app.tools.base import ApprovalRequired, ToolError

RESULT_CHARS = 12_000
EventFn = Callable[..., None]


@dataclass
class LoopResult:
    stop_reason: str  # final | max_steps | action_rejected | action_timeout | llm_unavailable
    final_text: str
    steps: int
    evidence: list[dict[str, Any]] = field(default_factory=list)
    actions_run: list[dict[str, Any]] = field(default_factory=list)


def _result_text(value: Any) -> str:
    s = json.dumps(value, default=str)
    if len(s) > RESULT_CHARS:
        s = s[:RESULT_CHARS] + f'... [truncated {len(s) - RESULT_CHARS} chars]'
    return s


def _tool_result(call_id: str, content: str, is_error: bool = False) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "tool_result", "tool_use_id": call_id, "content": content}
    if is_error:
        block["is_error"] = True
    return block


def _finalize(llm: LLM, system: str, messages: list[dict[str, Any]], instruction: str,
              fallback: str) -> str:
    """One last tool-less call so the model can write the report."""
    try:
        reply = llm.complete(
            system, messages + [{"role": "user", "content": instruction}], tools=None, max_tokens=1500)
        return reply.text.strip() or fallback
    except LLMUnavailable:
        return fallback


def run_loop(
    *,
    llm: LLM,
    system: str,
    user_message: str,
    tool_names: list[str],
    max_steps: int,
    incident_id: str | None,
    approval_timeout: float,
    on_event: EventFn,
    actor: str = "sre-agent",
    approvals: approvals_mod.ApprovalStore = approvals_mod.store,
) -> LoopResult:
    schemas = tools.schemas(tool_names)
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    result = LoopResult("final", "", 0)

    for step in range(1, max_steps + 1):
        result.steps = step
        try:
            reply = llm.complete(system, messages, tools=schemas)
        except LLMUnavailable as e:
            on_event("llm_error", error=str(e))
            result.stop_reason = "llm_unavailable"
            result.final_text = _evidence_summary(result, f"LLM unavailable: {e}")
            return result

        if reply.text.strip():
            on_event("assistant_text", step=step, text=reply.text.strip())
        messages.append({"role": "assistant", "content": reply.blocks})

        if not reply.tool_calls:
            result.final_text = reply.text.strip()
            return result

        tool_results: list[dict[str, Any]] = []
        stop_after: str | None = None
        for call in reply.tool_calls:
            if stop_after:
                tool_results.append(_tool_result(
                    call.id, "Skipped: an earlier action was not approved.", is_error=True))
                continue
            if call.name not in tool_names:
                on_event("tool_call", step=step, tool=call.name, input=call.input,
                         status="rejected", output="tool not available to this agent")
                tool_results.append(_tool_result(call.id, f"Unknown tool: {call.name}", True))
                continue

            spec = tools.TOOLS[call.name]
            approval_id: str | None = None
            if spec.kind == "action":
                outcome = _approve(spec, call, incident_id, approvals, approval_timeout, on_event, step)
                if outcome[0] == "invalid":  # bad arguments: the model may correct them
                    tool_results.append(_tool_result(call.id, outcome[1], is_error=True))
                    continue
                if outcome[0] != "approved":
                    tool_results.append(_tool_result(call.id, outcome[1], is_error=True))
                    stop_after = "action_rejected" if outcome[0] == "rejected" else "action_timeout"
                    continue
                approval_id = outcome[2]

            try:
                out = tools.call(call.name, call.input, incident_id=incident_id, approval_id=approval_id,
                                 actor=actor)
            except ApprovalRequired as e:
                on_event("tool_call", step=step, tool=call.name, input=call.input,
                         status="blocked", output=str(e))
                tool_results.append(_tool_result(call.id, str(e), True))
                continue
            except ToolError as e:
                on_event("tool_call", step=step, tool=call.name, input=call.input,
                         status="rejected", output=str(e))
                tool_results.append(_tool_result(call.id, f"Tool refused or failed: {e}", True))
                continue

            text = _result_text(out)
            on_event("tool_call", step=step, tool=call.name, input=call.input,
                     status="ok", output=text[:1500], approval_id=approval_id)
            result.evidence.append({"tool": call.name, "input": call.input, "output": text[:1500]})
            if spec.kind == "action":
                result.actions_run.append({"tool": call.name, "input": call.input, "result": out})
                text += ("\n\nNOTE: the approved action has run. Verify it worked with read-only "
                         "tools (container status and metrics) before concluding.")
            tool_results.append(_tool_result(call.id, text))

        messages.append({"role": "user", "content": tool_results})

        if stop_after:
            result.stop_reason = stop_after
            result.final_text = _finalize(
                llm, system, messages,
                "The proposed action was not approved, so no change was made. Write the final report: "
                "diagnosis with evidence, the action you proposed, and what the human should do next.",
                _evidence_summary(result, "Proposed action was not approved; no change was made."))
            return result

    result.stop_reason = "max_steps"
    result.final_text = _finalize(
        llm, system, messages,
        f"You reached the step limit ({max_steps}). Do not call tools. Report the evidence gathered "
        "so far, your best current hypothesis with its confidence, and what a human should check next.",
        _evidence_summary(result, f"Step limit ({max_steps}) reached without a conclusion."))
    return result


def _approve(spec, call, incident_id, approvals, timeout, on_event, step) -> tuple:
    """Ask for approval and block. Returns (status, message, approval_id)."""
    try:
        args = spec.model.model_validate(call.input).model_dump()
    except Exception as e:  # invalid input: let the registry reject it normally
        on_event("tool_call", step=step, tool=call.name, input=call.input,
                 status="rejected", output=f"invalid input: {e}")
        return ("invalid", f"Invalid input for {call.name}: {e}", None)
    item = approvals.request(call.name, args, incident_id, summary=spec.description,
                             timeout_seconds=int(timeout))
    on_event("approval_requested", step=step, approval_id=item.id, tool=call.name, args=args,
             expires_at=item.expires_at)
    status = approvals.wait(item.id, timeout)
    final = approvals.get(item.id)
    on_event("approval_decided", step=step, approval_id=item.id, tool=call.name, status=status,
             decided_by=final.decided_by if final else None)
    if status == "approved":
        return ("approved", "", item.id)
    if status == "rejected":
        return ("rejected", f"The human rejected {call.name}. Do not retry it.", item.id)
    return ("timeout", f"No approval for {call.name} within the time limit; action cancelled.", item.id)


def _evidence_summary(result: LoopResult, headline: str) -> str:
    lines = [headline, "", "Evidence gathered:"]
    for e in result.evidence:
        lines.append(f"- {e['tool']}({json.dumps(e['input'])}): {e['output'][:200]}")
    if not result.evidence:
        lines.append("- none")
    return "\n".join(lines)
