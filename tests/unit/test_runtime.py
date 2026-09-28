from pathlib import Path

from agentlab.adapters.fake import FakeAdapter
from agentlab.chaos import ChaosInjector
from agentlab.events import InMemoryEventSink
from agentlab.models import (
    FaultSpec,
    FaultType,
    FinalAnswer,
    ModelResponse,
    PolicyConfig,
    RunStatus,
    StrictModel,
    ToolCall,
    ToolResult,
)
from agentlab.policy import PolicyEngine
from agentlab.replay import ReplayEngine
from agentlab.runtime import AgentRuntime
from agentlab.store import FileEventStore
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

def test_runtime_budgets_unknown_tool_calls_before_registry_denial() -> None:
    adapter = FakeAdapter(
        script=[
            ModelResponse(
                action=ToolCall(
                    kind="tool",
                    call_id=f"unknown-{attempt}",
                    tool_name="hallucinated_tool",
                    arguments={"attempt": attempt},
                ),
                token_usage=1,
            )
            for attempt in range(3)
        ]
        + [ModelResponse(action=FinalAnswer(kind="final", content="不会到达"), token_usage=1)]
    )
    sink = InMemoryEventSink()
    runtime = AgentRuntime(
        adapter=adapter,
        event_sink=sink,
        seed=42,
        tools=ToolRegistry(),
        policy=PolicyEngine(PolicyConfig(max_tool_calls=2)),
    )

    result = runtime.run("调用不存在的工具", run_id="run-unknown-budget")

    assert result.status == RunStatus.TERMINATED
    assert result.final_answer is None
    assert sink.events[-1].type.value == "RunTerminated"
    assert sink.events[-1].payload["reason"] == "max_tool_calls_exceeded"

    event_types = [event.type.value for event in sink.events]
    assert event_types.count("ToolRequested") == 3
    assert event_types.count("PolicyEvaluated") == 3
    assert event_types.count("ToolFailed") == 2
    for index, event_type in enumerate(event_types):
        if event_type == "ToolRequested":
            assert event_types[index + 1] == "PolicyEvaluated"

    failed_results = [
        event.payload["result"]
        for event in sink.events
        if event.type.value == "ToolFailed"
    ]
    assert all(result["error"] == "unknown_tool" for result in failed_results)


def test_runtime_timeout_then_retry_can_complete(tmp_path: Path) -> None:
    adapter = FakeAdapter(
        script=[
            ModelResponse(
                action=ToolCall(
                    kind="tool",
                    call_id="1",
                    tool_name="search_docs",
                    arguments={"query": "x"},
                ),
                token_usage=5,
            ),
            ModelResponse(
                action=ToolCall(
                    kind="tool",
                    call_id="2",
                    tool_name="search_docs",
                    arguments={"query": "x"},
                ),
                token_usage=5,
            ),
            ModelResponse(action=FinalAnswer(kind="final", content="完成"), token_usage=3),
        ]
    )
    injector = ChaosInjector(
        [FaultSpec(type=FaultType.TIMEOUT, tool_name="search_docs", call_index=1)],
        seed=7,
    )
    runtime = AgentRuntime(
        adapter=adapter,
        event_sink=FileEventStore(tmp_path),
        tools=build_default_registry(),
        chaos=injector,
        seed=7,
    )

    result = runtime.run("查询 x", run_id="run-timeout")

    assert result.status == RunStatus.COMPLETED
    types = [event.type.value for event in FileEventStore(tmp_path).read_events(result.run_id)]
    assert "FaultInjected" in types
    assert "ToolFailed" in types
    assert types[-1] == "RunCompleted"


def test_runtime_tool_error_never_executes_handler() -> None:
    class EchoInput(StrictModel):
        value: int

    handler_calls = 0

    def handler(arguments: object) -> ToolResult:
        nonlocal handler_calls
        handler_calls += 1
        return ToolResult(call_id="", tool_name="echo", success=True, output=arguments)

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="echo",
            description="test fault injection",
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
                    arguments={"value": 1},
                ),
                token_usage=4,
            ),
            ModelResponse(action=FinalAnswer(kind="final", content="失败"), token_usage=2),
        ]
    )
    sink = InMemoryEventSink()
    runtime = AgentRuntime(
        adapter=adapter,
        event_sink=sink,
        seed=7,
        tools=registry,
        policy=PolicyEngine(PolicyConfig(allowed_tools={"echo"})),
        chaos=ChaosInjector(
            [FaultSpec(type=FaultType.TOOL_ERROR, tool_name="echo", call_index=1)],
            seed=7,
        ),
    )

    result = runtime.run("调用工具", run_id="run-tool-error")

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
        "FaultInjected",
        "ToolFailed",
        "ModelRequested",
        "ModelResponded",
        "RunCompleted",
    ]


def test_runtime_validates_tool_input_before_chaos(tmp_path: Path) -> None:
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
            description="test validation ordering",
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
                    arguments={"value": "invalid"},
                ),
                token_usage=4,
            ),
            ModelResponse(action=FinalAnswer(kind="final", content="验证失败"), token_usage=2),
        ]
    )
    store = FileEventStore(tmp_path)
    runtime = AgentRuntime(
        adapter=adapter,
        event_sink=store,
        seed=7,
        tools=registry,
        policy=PolicyEngine(PolicyConfig(allowed_tools={"echo"})),
        chaos=ChaosInjector(
            [FaultSpec(type=FaultType.TIMEOUT, tool_name="echo", call_index=1)],
            seed=7,
        ),
    )

    result = runtime.run("无效输入", run_id="run-validation-before-chaos")

    assert handler_calls == 0
    types = [event.type.value for event in store.read_events(result.run_id)]
    assert "FaultInjected" not in types
    tool_start = types.index("ToolStarted")
    assert types[tool_start : tool_start + 2] == ["ToolStarted", "ToolFailed"]


def test_extra_latency_metadata_does_not_change_event_or_state_hashes(tmp_path: Path) -> None:
    def run_once(root: Path) -> tuple[list[str], str, dict[str, object]]:
        adapter = FakeAdapter(
            script=[
                ModelResponse(
                    action=ToolCall(
                        kind="tool",
                        call_id="1",
                        tool_name="calculate",
                        arguments={"expression": "2+2"},
                    ),
                    token_usage=4,
                ),
                ModelResponse(action=FinalAnswer(kind="final", content="结果 4"), token_usage=2),
            ]
        )
        store = FileEventStore(root)
        result = AgentRuntime(
            adapter=adapter,
            event_sink=store,
            seed=11,
            tools=build_default_registry(),
            chaos=ChaosInjector(
                [
                    FaultSpec(
                        type=FaultType.EXTRA_LATENCY,
                        tool_name="calculate",
                        call_index=1,
                        payload={"delay_ms": 25},
                    )
                ],
                seed=11,
            ),
        ).run("计算", run_id="run-latency")
        events = store.read_events(result.run_id)
        tool_result = next(
            event.payload["result"]
            for event in events
            if event.type.value == "ToolSucceeded"
        )
        assert isinstance(tool_result, dict)
        return [event.hash for event in events], result.state_hash, tool_result

    first_hashes, first_state_hash, first_tool_result = run_once(tmp_path / "first")
    second_hashes, second_state_hash, second_tool_result = run_once(tmp_path / "second")

    assert first_hashes == second_hashes
    assert first_state_hash == second_state_hash
    assert first_tool_result == second_tool_result
    assert first_tool_result["duration_ms"] == 0.0
    assert first_tool_result["metadata"]["fault_injected"] == "extra_latency"
    assert first_tool_result["metadata"]["delay_ms"] == 25


def test_runtime_applies_after_tool_fault_to_successful_result(tmp_path: Path) -> None:
    adapter = FakeAdapter(
        script=[
            ModelResponse(
                action=ToolCall(
                    kind="tool",
                    call_id="1",
                    tool_name="fetch_record",
                    arguments={"record_id": "1"},
                ),
                token_usage=4,
            ),
            ModelResponse(action=FinalAnswer(kind="final", content="记录不可解析"), token_usage=2),
        ]
    )
    store = FileEventStore(tmp_path)
    runtime = AgentRuntime(
        adapter=adapter,
        event_sink=store,
        seed=4,
        tools=build_default_registry(),
        chaos=ChaosInjector(
            [
                FaultSpec(
                    type=FaultType.MALFORMED_JSON,
                    tool_name="fetch_record",
                    call_index=1,
                )
            ],
            seed=4,
        ),
    )

    result = runtime.run("读取记录", run_id="run-malformed")

    events = store.read_events(result.run_id)
    types = [event.type.value for event in events]
    tool_start = types.index("ToolStarted")
    assert types[tool_start : tool_start + 3] == [
        "ToolStarted",
        "FaultInjected",
        "ToolSucceeded",
    ]
    tool_result = next(
        event.payload["result"] for event in events if event.type.value == "ToolSucceeded"
    )
    assert tool_result["output"] == "{not-json"
    assert tool_result["metadata"]["fault_injected"] == "malformed_json"


def test_replay_reconstructs_faulted_run_without_rerunning_injection(tmp_path: Path) -> None:
    adapter = FakeAdapter(
        script=[
            ModelResponse(
                action=ToolCall(
                    kind="tool",
                    call_id="1",
                    tool_name="search_docs",
                    arguments={"query": "x"},
                ),
                token_usage=4,
            ),
            ModelResponse(
                action=ToolCall(
                    kind="tool",
                    call_id="2",
                    tool_name="search_docs",
                    arguments={"query": "x"},
                ),
                token_usage=4,
            ),
            ModelResponse(action=FinalAnswer(kind="final", content="完成"), token_usage=2),
        ]
    )
    store = FileEventStore(tmp_path)
    runtime = AgentRuntime(
        adapter=adapter,
        event_sink=store,
        seed=7,
        tools=build_default_registry(),
        chaos=ChaosInjector(
            [FaultSpec(type=FaultType.TIMEOUT, tool_name="search_docs", call_index=1)],
            seed=7,
        ),
    )

    record = runtime.run("查询 x", run_id="run-replay-fault")
    events = store.read_events(record.run_id)
    replayed = ReplayEngine(store).replay(record.run_id)

    assert sum(event.type.value == "FaultInjected" for event in events) == 1
    assert replayed.status == record.status
    assert replayed.state_hash == record.state_hash
