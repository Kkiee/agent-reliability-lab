from agentlab.adapters.fake import FakeAdapter
from agentlab.events import InMemoryEventSink
from agentlab.models import (
    FinalAnswer,
    ModelResponse,
    PolicyConfig,
    RunStatus,
    StrictModel,
    ToolCall,
    ToolResult,
)
from agentlab.policy import PolicyEngine
from agentlab.runtime import AgentRuntime
from agentlab.tools.base import ToolRegistry, ToolSpec
from agentlab.tools.builtin import build_default_registry


def test_runtime_completes_final_answer() -> None:
    adapter = FakeAdapter(
        script=[ModelResponse(action=FinalAnswer(kind="final", content="你好"), token_usage=7)]
    )
    sink = InMemoryEventSink()
    runtime = AgentRuntime(adapter=adapter, event_sink=sink, seed=42)

    result = runtime.run("打个招呼", run_id="run-1")

    assert result.status == RunStatus.COMPLETED
    assert result.final_answer == "你好"
    assert result.steps == 1
    assert result.token_usage == 7
    assert [event.type.value for event in sink.events] == [
        "RunStarted",
        "ModelRequested",
        "ModelResponded",
        "RunCompleted",
    ]


def test_runtime_event_hashes_are_deterministic_for_identical_runs() -> None:
    def run_once() -> list[str]:
        adapter = FakeAdapter(
            script=[ModelResponse(action=FinalAnswer(kind="final", content="你好"), token_usage=7)]
        )
        sink = InMemoryEventSink()
        AgentRuntime(adapter=adapter, event_sink=sink, seed=42).run("打个招呼", run_id="run-1")
        return [event.hash for event in sink.events]

    first = run_once()
    second = run_once()

    assert first == second
    assert len(first) == 4


def test_runtime_executes_allowed_tool_and_continues_to_final_answer() -> None:
    adapter = FakeAdapter(
        script=[
            ModelResponse(
                action=ToolCall(
                    kind="tool",
                    call_id="call-1",
                    tool_name="calculate",
                    arguments={"expression": "2+2"},
                ),
                token_usage=4,
            ),
            ModelResponse(action=FinalAnswer(kind="final", content="结果是 4"), token_usage=3),
        ]
    )
    sink = InMemoryEventSink()
    runtime = AgentRuntime(
        adapter=adapter,
        event_sink=sink,
        seed=42,
        tools=build_default_registry(),
    )

    result = runtime.run("计算 2+2", run_id="run-tool")

    assert result.status == RunStatus.COMPLETED
    assert result.final_answer == "结果是 4"
    assert [event.type.value for event in sink.events] == [
        "RunStarted",
        "ModelRequested",
        "ModelResponded",
        "ToolRequested",
        "PolicyEvaluated",
        "ToolStarted",
        "ToolSucceeded",
        "ModelRequested",
        "ModelResponded",
        "RunCompleted",
    ]
    tool_event = next(event for event in sink.events if event.type.value == "ToolSucceeded")
    assert tool_event.payload["result"] == {
        "call_id": "call-1",
        "tool_name": "calculate",
        "success": True,
        "output": 4,
        "error": None,
        "duration_ms": 0.0,
        "metadata": {},
    }


def test_runtime_feeds_policy_denial_to_next_model_step() -> None:
    class CapturingAdapter:
        model_name = "capturing"

        def __init__(self, script: list[ModelResponse]) -> None:
            self._script = script
            self.prompts: list[str] = []

        def complete(self, prompt: str, step: int) -> ModelResponse:
            self.prompts.append(prompt)
            return self._script[step - 1]

    adapter = CapturingAdapter(
        [
            ModelResponse(
                action=ToolCall(
                    kind="tool",
                    call_id="call-1",
                    tool_name="send_message",
                    arguments={"recipient": "user-1", "text": "hello"},
                ),
                token_usage=5,
            ),
            ModelResponse(action=FinalAnswer(kind="final", content="发送被拒绝"), token_usage=2),
        ]
    )
    sink = InMemoryEventSink()
    policy = PolicyEngine(
        PolicyConfig(allowed_tools={"send_message"}, allow_side_effects=False)
    )
    runtime = AgentRuntime(
        adapter=adapter,
        event_sink=sink,
        seed=42,
        tools=build_default_registry(),
        policy=policy,
    )

    result = runtime.run("发送消息", run_id="run-denied")

    assert result.status == RunStatus.COMPLETED
    assert "side_effect_not_allowed" in adapter.prompts[1]
    types = [event.type.value for event in sink.events]
    assert types == [
        "RunStarted",
        "ModelRequested",
        "ModelResponded",
        "ToolRequested",
        "PolicyEvaluated",
        "ModelRequested",
        "ModelResponded",
        "RunCompleted",
    ]


def test_runtime_validates_tool_input_before_handler_execution() -> None:
    class EchoInput(StrictModel):
        value: int

    handler_calls = 0

    def handler(arguments: object) -> ToolResult:
        nonlocal handler_calls
        handler_calls += 1
        return ToolResult(call_id="", tool_name="echo", success=True)

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="echo",
            description="test validation",
            input_model=EchoInput,
            handler=handler,
        )
    )
    adapter = FakeAdapter(
        script=[
            ModelResponse(
                action=ToolCall(
                    kind="tool",
                    call_id="call-1",
                    tool_name="echo",
                    arguments={"value": "not-an-int"},
                ),
                token_usage=4,
            ),
            ModelResponse(action=FinalAnswer(kind="final", content="验证失败"), token_usage=2),
        ]
    )
    sink = InMemoryEventSink()
    runtime = AgentRuntime(
        adapter=adapter,
        event_sink=sink,
        seed=42,
        tools=registry,
        policy=PolicyEngine(PolicyConfig(allowed_tools={"echo"})),
    )

    result = runtime.run("触发无效输入", run_id="run-invalid-tool")

    assert result.status == RunStatus.COMPLETED
    assert handler_calls == 0
    types = [event.type.value for event in sink.events]
    assert types == [
        "RunStarted",
        "ModelRequested",
        "ModelResponded",
        "ToolRequested",
        "PolicyEvaluated",
        "ToolStarted",
        "ToolFailed",
        "ModelRequested",
        "ModelResponded",
        "RunCompleted",
    ]


def test_runtime_terminates_repeated_tool_call() -> None:
    call = ToolCall(
        kind="tool",
        call_id="call",
        tool_name="search_docs",
        arguments={"query": "same"},
    )
    adapter = FakeAdapter(
        script=[
            ModelResponse(action=call.model_copy(update={"call_id": "call-1"}), token_usage=2),
            ModelResponse(action=call.model_copy(update={"call_id": "call-2"}), token_usage=2),
            ModelResponse(action=call.model_copy(update={"call_id": "call-3"}), token_usage=2),
            ModelResponse(action=FinalAnswer(kind="final", content="不会到达"), token_usage=1),
        ]
    )
    sink = InMemoryEventSink()
    runtime = AgentRuntime(
        adapter=adapter,
        event_sink=sink,
        seed=42,
        tools=build_default_registry(),
        policy=PolicyEngine(PolicyConfig(repeated_call_limit=3)),
    )

    result = runtime.run("重复查询", run_id="run-loop")

    assert result.status == RunStatus.TERMINATED
    types = [event.type.value for event in sink.events]
    assert types.count("ToolRequested") == 3
    assert types.count("ToolSucceeded") == 2
    assert types.count("ToolStarted") == 2
    assert types[-1] == "RunTerminated"
