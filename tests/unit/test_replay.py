import json
from pathlib import Path

import pytest

from agentlab.adapters.fake import FakeAdapter
from agentlab.models import (
    FinalAnswer,
    ModelResponse,
    PolicyConfig,
    RunRecord,
    RunStatus,
    ToolCall,
)
from agentlab.policy import PolicyEngine
from agentlab.replay import ReplayEngine
from agentlab.runtime import AgentRuntime
from agentlab.store import EventIntegrityError, FileEventStore
from agentlab.tools.base import ToolRegistry
from agentlab.tools.builtin import build_default_registry


def run_saved_happy_path(root: Path) -> RunRecord:
    store = FileEventStore(root)
    runtime = AgentRuntime(
        adapter=FakeAdapter(
            [ModelResponse(action=FinalAnswer(kind="final", content="你好"), token_usage=7)]
        ),
        event_sink=store,
        seed=42,
    )
    return runtime.run("打个招呼", run_id="run-1")


def run_saved_denied_tool_path(root: Path) -> RunRecord:
    store = FileEventStore(root)
    runtime = AgentRuntime(
        adapter=FakeAdapter(
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
                ModelResponse(
                    action=FinalAnswer(kind="final", content="发送被拒绝"),
                    token_usage=2,
                ),
            ]
        ),
        event_sink=store,
        seed=42,
        tools=build_default_registry(),
        policy=PolicyEngine(
            PolicyConfig(allowed_tools={"send_message"}, allow_side_effects=False)
        ),
    )
    return runtime.run("发送消息", run_id="run-denied")


def test_replay_does_not_call_adapter_or_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = run_saved_happy_path(tmp_path)

    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError("replay must not call adapters or tools")

    monkeypatch.setattr(FakeAdapter, "complete", fail)
    monkeypatch.setattr(ToolRegistry, "get", fail)
    restored = ReplayEngine(tmp_path).replay(original.run_id)

    assert restored.status == RunStatus.COMPLETED
    assert restored.final_answer == "你好"
    assert restored.steps == 1
    assert restored.token_usage == 7
    assert restored.state_hash == original.state_hash


def test_replay_reconstructs_policy_denied_results(tmp_path: Path) -> None:
    original = run_saved_denied_tool_path(tmp_path)

    restored = ReplayEngine(tmp_path).replay(original.run_id)

    assert restored.status == original.status
    assert restored.final_answer == original.final_answer
    assert restored.state_hash == original.state_hash


def test_replay_rejects_tampered_event_before_reconstructing_state(tmp_path: Path) -> None:
    original = run_saved_happy_path(tmp_path)
    path = tmp_path / original.run_id / "events.jsonl"
    path.write_text(
        path.read_text(encoding="utf-8").replace('"你好"', '"tampered"'),
        encoding="utf-8",
    )

    with pytest.raises(EventIntegrityError):
        ReplayEngine(tmp_path).replay(original.run_id)


def test_replay_rejects_tampered_state_snapshot(tmp_path: Path) -> None:
    original = run_saved_happy_path(tmp_path)
    path = tmp_path / original.run_id / "state.json"
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    snapshot["state"]["final_answer"] = "tampered"
    path.write_text(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(EventIntegrityError):
        ReplayEngine(tmp_path).replay(original.run_id)


def test_replay_engine_accepts_existing_file_store(tmp_path: Path) -> None:
    store = FileEventStore(tmp_path)
    record = AgentRuntime(
        adapter=FakeAdapter(
            [ModelResponse(action=FinalAnswer(kind="final", content="done"), token_usage=3)]
        ),
        event_sink=store,
        seed=7,
    ).run("prompt", run_id="run-store")

    restored = ReplayEngine(store).replay(record.run_id)

    assert restored.state_hash == record.state_hash
