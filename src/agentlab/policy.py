from __future__ import annotations

import json
from enum import StrEnum

from agentlab.models import PolicyConfig, RuntimeState, StrictModel, ToolCall
from agentlab.tools.base import ToolSpec


class PolicyDecisionType(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    TERMINATE = "terminate"


class PolicyDecision(StrictModel):
    kind: PolicyDecisionType
    reason: str


class PolicyEngine:
    def __init__(self, config: PolicyConfig) -> None:
        self.config = config

    def evaluate(
        self,
        call: ToolCall,
        spec: ToolSpec | None,
        state: RuntimeState,
    ) -> PolicyDecision:
        if state.step >= self.config.max_steps:
            return PolicyDecision(
                kind=PolicyDecisionType.TERMINATE,
                reason="max_steps_exceeded",
            )
        if state.tool_calls >= self.config.max_tool_calls:
            return PolicyDecision(
                kind=PolicyDecisionType.TERMINATE,
                reason="max_tool_calls_exceeded",
            )
        if state.token_usage >= self.config.max_tokens:
            return PolicyDecision(
                kind=PolicyDecisionType.TERMINATE,
                reason="token_budget_exceeded",
            )
        if spec is None:
            return PolicyDecision(kind=PolicyDecisionType.DENY, reason="unknown_tool")
        if call.tool_name in self.config.blocked_tools:
            return PolicyDecision(kind=PolicyDecisionType.DENY, reason="tool_blocked")
        if call.tool_name not in self.config.allowed_tools:
            return PolicyDecision(kind=PolicyDecisionType.DENY, reason="tool_not_allowed")
        if self._repeated_call_count(call, state) + 1 >= self.config.repeated_call_limit:
            return PolicyDecision(
                kind=PolicyDecisionType.TERMINATE,
                reason="repeated_tool_call",
            )
        if spec.side_effect and not self.config.allow_side_effects:
            return PolicyDecision(
                kind=PolicyDecisionType.DENY,
                reason="side_effect_not_allowed",
            )
        if call.tool_name in self.config.approval_required_tools:
            return PolicyDecision(kind=PolicyDecisionType.DENY, reason="approval_required")
        return PolicyDecision(kind=PolicyDecisionType.ALLOW, reason="allowed")

    def _repeated_call_count(self, call: ToolCall, state: RuntimeState) -> int:
        normalized = json.dumps(
            call.arguments,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return sum(
            previous.tool_name == call.tool_name
            and json.dumps(
                previous.arguments,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            == normalized
            for previous in state.history
        )