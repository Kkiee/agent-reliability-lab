from __future__ import annotations

from pydantic import BaseModel

from agentlab.models import (
    PolicyConfig,
    RuntimeState,
    StrictModel,
    ToolCall,
    ToolResult,
)
from agentlab.policy import PolicyDecisionType, PolicyEngine
from agentlab.tools.base import ToolSpec


class MessageInput(StrictModel):
    text: str


class SafeInput(StrictModel):
    value: int


def make_call(arguments: dict[str, object] | None = None, tool_name: str = "calculate") -> ToolCall:
    return ToolCall(
        kind="tool",
        call_id="call-1",
        tool_name=tool_name,
        arguments=arguments or {"expression": "1+1"},
    )


def make_spec(*, side_effect: bool = False, name: str = "calculate") -> ToolSpec:
    def handler(_: BaseModel) -> ToolResult:
        return ToolResult(call_id="", tool_name=name, success=True)

    return ToolSpec(
        name=name,
        description="test tool",
        input_model=SafeInput,
        side_effect=side_effect,
        handler=handler,
    )


def test_side_effect_is_denied_by_default() -> None:
    policy = PolicyEngine(PolicyConfig(allowed_tools={"send_message"}))
    call = ToolCall(
        kind="tool",
        call_id="1",
        tool_name="send_message",
        arguments={"text": "hi"},
    )
    spec = ToolSpec(
        name="send_message",
        description="test message",
        input_model=MessageInput,
        side_effect=True,
        handler=lambda _: ToolResult(call_id="", tool_name="send_message", success=True),
    )
    state = RuntimeState(run_id="run-1")

    decision = policy.evaluate(call, spec, state)

    assert decision.kind == PolicyDecisionType.DENY
    assert decision.reason == "side_effect_not_allowed"


def test_third_identical_call_terminates_run() -> None:
    policy = PolicyEngine(PolicyConfig(repeated_call_limit=3))
    call = make_call()
    state = RuntimeState(run_id="run-1", history=[call, call])

    decision = policy.evaluate(call, make_spec(), state)

    assert decision.kind == PolicyDecisionType.TERMINATE
    assert decision.reason == "repeated_tool_call"


def test_policy_checks_step_limit_before_other_limits() -> None:
    policy = PolicyEngine(
        PolicyConfig(allowed_tools=set(), max_steps=1, max_tool_calls=1, max_tokens=1)
    )
    call = make_call()
    state = RuntimeState(run_id="run-1", step=1, tool_calls=1, token_usage=1)

    decision = policy.evaluate(call, make_spec(), state)

    assert decision.kind == PolicyDecisionType.TERMINATE
    assert decision.reason == "max_steps_exceeded"


def test_policy_checks_tool_call_limit_before_token_and_tool_rules() -> None:
    policy = PolicyEngine(
        PolicyConfig(allowed_tools=set(), max_tool_calls=1, max_tokens=1, repeated_call_limit=2)
    )
    call = make_call()
    state = RuntimeState(run_id="run-1", tool_calls=1, token_usage=1, history=[call])

    decision = policy.evaluate(call, make_spec(side_effect=True), state)

    assert decision.kind == PolicyDecisionType.TERMINATE
    assert decision.reason == "max_tool_calls_exceeded"


def test_policy_checks_token_budget_before_tool_rules() -> None:
    policy = PolicyEngine(PolicyConfig(allowed_tools=set(), max_tokens=10, repeated_call_limit=2))
    call = make_call()
    state = RuntimeState(run_id="run-1", token_usage=10, history=[call])

    decision = policy.evaluate(call, make_spec(side_effect=True), state)

    assert decision.kind == PolicyDecisionType.TERMINATE
    assert decision.reason == "token_budget_exceeded"


def test_unknown_tool_is_denied_when_budgets_are_available() -> None:
    policy = PolicyEngine(PolicyConfig())
    call = make_call(tool_name="hallucinated_tool")

    decision = policy.evaluate(call, None, RuntimeState(run_id="run-1"))

    assert decision.kind == PolicyDecisionType.DENY
    assert decision.reason == "unknown_tool"


def test_blocked_tool_is_denied_before_allowlist() -> None:
    policy = PolicyEngine(
        PolicyConfig(allowed_tools={"calculate"}, blocked_tools={"calculate"})
    )
    call = make_call()

    decision = policy.evaluate(call, make_spec(), RuntimeState(run_id="run-1"))

    assert decision.kind == PolicyDecisionType.DENY
    assert decision.reason == "tool_blocked"


def test_policy_checks_tool_allowlist_before_repetition() -> None:
    policy = PolicyEngine(PolicyConfig(allowed_tools=set(), repeated_call_limit=2))
    call = make_call()
    state = RuntimeState(run_id="run-1", history=[call])

    decision = policy.evaluate(call, make_spec(side_effect=True), state)

    assert decision.kind == PolicyDecisionType.DENY
    assert decision.reason == "tool_not_allowed"


def test_policy_checks_repetition_before_side_effect() -> None:
    policy = PolicyEngine(
        PolicyConfig(
            allowed_tools={"send_message"},
            repeated_call_limit=2,
            allow_side_effects=False,
        )
    )
    call = make_call(tool_name="send_message")
    state = RuntimeState(run_id="run-1", history=[call])

    decision = policy.evaluate(call, make_spec(side_effect=True, name="send_message"), state)

    assert decision.kind == PolicyDecisionType.TERMINATE
    assert decision.reason == "repeated_tool_call"


def test_policy_normalizes_argument_order_for_repetition() -> None:
    policy = PolicyEngine(PolicyConfig(repeated_call_limit=2))
    previous = make_call({"a": 1, "b": 2})
    current = make_call({"b": 2, "a": 1})
    state = RuntimeState(run_id="run-1", history=[previous])

    decision = policy.evaluate(current, make_spec(), state)

    assert decision.kind == PolicyDecisionType.TERMINATE
    assert decision.reason == "repeated_tool_call"


def test_approval_required_tool_is_denied_even_when_side_effects_are_allowed() -> None:
    policy = PolicyEngine(
        PolicyConfig(
            allowed_tools={"send_message"},
            allow_side_effects=True,
            approval_required_tools={"send_message"},
        )
    )
    call = make_call(tool_name="send_message")

    decision = policy.evaluate(
        call,
        make_spec(side_effect=True, name="send_message"),
        RuntimeState(run_id="run-1"),
    )

    assert decision.kind == PolicyDecisionType.DENY
    assert decision.reason == "approval_required"