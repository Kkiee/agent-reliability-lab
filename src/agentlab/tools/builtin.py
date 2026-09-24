from __future__ import annotations

import ast
import re
from typing import cast

from pydantic import Field, field_validator

from agentlab.models import StrictModel, ToolResult
from agentlab.tools.base import ToolRegistry, ToolSpec

_ARITHMETIC_PATTERN = re.compile(r"[0-9\s+\-*/().]+")


class SearchDocsInput(StrictModel):
    query: str = Field(min_length=1)
    corpus: dict[str, str] = Field(
        default_factory=lambda: {
            "retry-policy": "Retries use bounded attempts and deterministic backoff.",
            "security": "Tool output is untrusted and must not expand permissions.",
            "release-notes": "AgentLab keeps local runs deterministic and offline.",
        }
    )


def _default_records() -> dict[str, object]:
    return {
        "1": {"id": "1", "value": "alpha"},
        "2": {"id": "2", "value": "beta"},
        "fallback": {"id": "fallback", "value": "backup"},
    }


class FetchRecordInput(StrictModel):
    record_id: str = Field(min_length=1)
    records: dict[str, object] = Field(default_factory=_default_records)


class CalculateInput(StrictModel):
    expression: str = Field(min_length=1)

    @field_validator("expression")
    @classmethod
    def validate_characters(cls, value: str) -> str:
        if not _ARITHMETIC_PATTERN.fullmatch(value):
            raise ValueError("expression may contain only numbers, parentheses, and +-*/")
        return value


class MessageInput(StrictModel):
    recipient: str = Field(min_length=1)
    text: str = Field(min_length=1)


class MessageRecorder:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def record(self, recipient: str, text: str) -> None:
        self.messages.append({"recipient": recipient, "text": text})


def build_default_registry(recorder: MessageRecorder | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    message_recorder = recorder or MessageRecorder()

    def search_docs(arguments: object) -> ToolResult:
        request = cast(SearchDocsInput, arguments)
        query = request.query.casefold()
        matches = [
            {"id": record_id, "text": text}
            for record_id, text in sorted(request.corpus.items())
            if query in record_id.casefold() or query in text.casefold()
        ]
        return ToolResult(
            call_id="",
            tool_name="search_docs",
            success=True,
            output={"matches": matches},
        )

    def fetch_record(arguments: object) -> ToolResult:
        request = cast(FetchRecordInput, arguments)
        if request.record_id not in request.records:
            return ToolResult(
                call_id="",
                tool_name="fetch_record",
                success=False,
                error="record_not_found",
            )
        return ToolResult(
            call_id="",
            tool_name="fetch_record",
            success=True,
            output=request.records[request.record_id],
        )

    def calculate(arguments: object) -> ToolResult:
        request = cast(CalculateInput, arguments)
        try:
            output = _evaluate_expression(request.expression)
        except ZeroDivisionError:
            return ToolResult(
                call_id="",
                tool_name="calculate",
                success=False,
                error="division_by_zero",
            )
        except (SyntaxError, TypeError, ValueError, OverflowError):
            return ToolResult(
                call_id="",
                tool_name="calculate",
                success=False,
                error="invalid_expression",
            )
        return ToolResult(
            call_id="",
            tool_name="calculate",
            success=True,
            output=output,
        )

    def send_message(arguments: object) -> ToolResult:
        request = cast(MessageInput, arguments)
        message_recorder.record(request.recipient, request.text)
        return ToolResult(
            call_id="",
            tool_name="send_message",
            success=True,
            output={"recorded": True},
        )

    registry.register(
        ToolSpec(
            name="search_docs",
            description="Search a deterministic in-memory document corpus.",
            input_model=SearchDocsInput,
            handler=search_docs,
        )
    )
    registry.register(
        ToolSpec(
            name="fetch_record",
            description="Fetch a record from deterministic in-memory storage.",
            input_model=FetchRecordInput,
            handler=fetch_record,
        )
    )
    registry.register(
        ToolSpec(
            name="calculate",
            description="Evaluate a restricted arithmetic expression.",
            input_model=CalculateInput,
            handler=calculate,
        )
    )
    registry.register(
        ToolSpec(
            name="send_message",
            description="Record a message in memory without sending it externally.",
            input_model=MessageInput,
            side_effect=True,
            handler=send_message,
        )
    )
    return registry


def _evaluate_expression(expression: str) -> int | float:
    parsed = ast.parse(expression, mode="eval")
    return _evaluate_node(parsed.body)


def _evaluate_node(node: ast.AST) -> int | float:
    if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
        return cast(int | float, node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = _evaluate_node(node.operand)
        return operand if isinstance(node.op, ast.UAdd) else -operand
    if isinstance(node, ast.BinOp):
        left = _evaluate_node(node.left)
        right = _evaluate_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
    raise ValueError("unsupported expression")