from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from pydantic import BaseModel

from agentlab.models import StrictModel, ToolResult


class ToolHandler(Protocol):
    def __call__(self, arguments: BaseModel) -> ToolResult: ...


class ToolSpec(StrictModel):
    name: str
    description: str
    input_model: type[BaseModel]
    side_effect: bool = False
    handler: Callable[[BaseModel], ToolResult]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)