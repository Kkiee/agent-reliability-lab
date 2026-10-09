from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActionType(StrEnum):
    TOOL = "tool"
    FINAL = "final"


class FaultType(StrEnum):
    TIMEOUT = "timeout"
    TOOL_ERROR = "tool_error"
    MALFORMED_JSON = "malformed_json"
    EMPTY_RESULT = "empty_result"
    EXTRA_LATENCY = "extra_latency"
    DUPLICATE_RESULT = "duplicate_result"
    PROMPT_INJECTION = "prompt_injection"
    CONTRADICTORY_RESULT = "contradictory_result"


class EventType(StrEnum):
    RUN_STARTED = "RunStarted"
    MODEL_REQUESTED = "ModelRequested"
    MODEL_RESPONDED = "ModelResponded"
    TOOL_REQUESTED = "ToolRequested"
    POLICY_EVALUATED = "PolicyEvaluated"
    TOOL_STARTED = "ToolStarted"
    TOOL_SUCCEEDED = "ToolSucceeded"
    TOOL_FAILED = "ToolFailed"
    FAULT_INJECTED = "FaultInjected"
    RUN_COMPLETED = "RunCompleted"
    RUN_FAILED = "RunFailed"
    RUN_TERMINATED = "RunTerminated"


class RunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_FOR_MODEL = "waiting_for_model"
    WAITING_FOR_TOOL = "waiting_for_tool"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"


class ToolCall(StrictModel):
    kind: Literal["tool"] = "tool"
    call_id: str
    tool_name: str
    arguments: dict[str, object]


class FinalAnswer(StrictModel):
    kind: Literal["final"] = "final"
    content: str


Action = Annotated[ToolCall | FinalAnswer, Field(discriminator="kind")]


class ModelResponse(StrictModel):
    action: Action
    token_usage: int = Field(ge=0)


class PolicyConfig(StrictModel):
    allowed_tools: set[str] = Field(
        default_factory=lambda: {"search_docs", "fetch_record", "calculate"}
    )
    blocked_tools: set[str] = Field(default_factory=set)
    max_steps: int = Field(default=12, ge=1)
    max_tool_calls: int = Field(default=8, ge=1)
    max_tokens: int = Field(default=6000, ge=1)
    repeated_call_limit: int = Field(default=3, ge=2)
    allow_side_effects: bool = False
    approval_required_tools: set[str] = Field(default_factory=set)


class FaultSpec(StrictModel):
    type: FaultType
    tool_name: str = Field(min_length=1)
    call_index: int = Field(ge=1)
    probability: float = Field(default=1.0, ge=0.0, le=1.0)
    message: str = ""
    payload: dict[str, object] = Field(default_factory=dict)


class ToolResult(StrictModel):
    call_id: str
    tool_name: str
    success: bool
    output: object | None = None
    error: str | None = None
    duration_ms: float = 0.0
    metadata: dict[str, object] = Field(default_factory=dict)


class RuntimeState(StrictModel):
    run_id: str
    status: RunStatus = RunStatus.CREATED
    step: int = 0
    tool_calls: int = 0
    token_usage: int = 0
    history: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    final_answer: str | None = None
    termination_reason: str | None = None


class RunRecord(StrictModel):
    run_id: str
    status: RunStatus
    final_answer: str | None = None
    steps: int = 0
    token_usage: int = 0
    state_hash: str = ""


class ExpectedBehavior(StrictModel):
    status: RunStatus
    final_answer_contains: str | None = None
    recovered: bool | None = None
    max_policy_violations: int = Field(default=0, ge=0)
    min_policy_denials: int = Field(default=0, ge=0)
    required_events: list[EventType] = Field(default_factory=list)
    min_tool_calls: int = Field(default=0, ge=0)
    max_tool_calls: int | None = Field(default=None, ge=0)


class Scenario(StrictModel):
    name: str
    description: str = ""
    user_input: str
    model_script: list[ModelResponse]
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    faults: list[FaultSpec] = Field(default_factory=list)
    expected: ExpectedBehavior
