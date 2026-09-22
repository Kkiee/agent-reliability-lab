from agentlab.adapters.fake import FakeAdapter
from agentlab.events import InMemoryEventSink
from agentlab.models import FinalAnswer, ModelResponse, RunStatus
from agentlab.runtime import AgentRuntime


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
