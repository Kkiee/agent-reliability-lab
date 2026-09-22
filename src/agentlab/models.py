from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActionType(StrEnum):
    TOOL = "tool"
    FINAL = "final"


class EventType(StrEnum):
    RUN_STARTED = "RunStarted"
    MODEL_REQUESTED = "ModelRequested"
    MODEL_RESPONDED = "ModelResponded"
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


class RunRecord(StrictModel):
    run_id: str
    status: RunStatus
    final_answer: str | None = None
    steps: int = 0
    token_usage: int = 0
    state_hash: str = ""
