import pytest
from pydantic import ValidationError

from agentlab.models import ActionType, FinalAnswer, ModelResponse, ToolCall


def test_final_answer_is_valid_action() -> None:
    action = FinalAnswer(kind="final", content="完成")
    response = ModelResponse(action=action, token_usage=12)

    assert response.action.kind == ActionType.FINAL
    assert response.token_usage == 12


def test_tool_call_requires_object_arguments() -> None:
    with pytest.raises(ValidationError):
        ToolCall(kind="tool", call_id="call-1", tool_name="calculate", arguments="1+1")


def test_model_response_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ModelResponse.model_validate(
            {"action": {"kind": "final", "content": "ok"}, "token_usage": 1, "unknown": True}
        )
