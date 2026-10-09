from __future__ import annotations

from pathlib import Path

from agentlab.evaluator import Evaluator, evaluate_suite
from agentlab.events import Event
from agentlab.models import (
    EventType,
    ExpectedBehavior,
    FinalAnswer,
    ModelResponse,
    RunRecord,
    RunStatus,
    Scenario,
)


def _event(seq: int, event_type: EventType, payload: dict[str, object]) -> Event:
    return Event(
        event_id=f"event-{seq}",
        run_id="run-1",
        seq=seq,
        type=event_type,
        timestamp=f"2026-09-22T10:00:{seq:02d}+00:00",
        payload=payload,
    )


def _run(status: RunStatus = RunStatus.COMPLETED) -> RunRecord:
    return RunRecord(
        run_id="run-1",
        status=status,
        final_answer="done" if status == RunStatus.COMPLETED else None,
        steps=2,
        token_usage=10,
        state_hash="state-hash",
    )


def test_trace_completeness_rewards_required_events() -> None:
    events = [
        _event(1, EventType.RUN_STARTED, {"seed": 42, "prompt": "finish"}),
        _event(2, EventType.FAULT_INJECTED, {"fault_type": "timeout"}),
        _event(
            3,
            EventType.TOOL_SUCCEEDED,
            {
                "result": {
                    "call_id": "call-1",
                    "tool_name": "search_docs",
                    "success": True,
                    "output": {},
                    "error": None,
                    "duration_ms": 5.0,
                    "metadata": {},
                }
            },
        ),
        _event(4, EventType.RUN_COMPLETED, {"final_answer": "done"}),
    ]
    expected = ExpectedBehavior(
        status=RunStatus.COMPLETED,
        final_answer_contains="done",
        recovered=True,
        required_events=[EventType.FAULT_INJECTED, EventType.TOOL_SUCCEEDED],
    )

    result = Evaluator().evaluate(_run(), events, expected, replay=_run())

    assert result.metrics["trace_completeness"] == 1.0
    assert result.metrics["task_success"] == 1.0
    assert result.metrics["recovery_rate"] == 1.0
    assert result.passed is True


def test_missing_required_event_fails_scenario() -> None:
    events = [_event(1, EventType.RUN_STARTED, {"seed": 42, "prompt": "finish"})]
    expected = ExpectedBehavior(
        status=RunStatus.COMPLETED,
        required_events=[EventType.FAULT_INJECTED],
    )

    result = Evaluator().evaluate(_run(), events, expected, replay=_run())

    assert result.passed is False
    assert "missing_required_event:FaultInjected" in result.failures


def test_task_success_requires_expected_status_and_final_answer() -> None:
    events = [_event(1, EventType.RUN_COMPLETED, {"final_answer": "done"})]

    success = Evaluator().evaluate(
        _run(),
        events,
        ExpectedBehavior(status=RunStatus.COMPLETED, final_answer_contains="done"),
        replay=_run(),
    )
    mismatch = Evaluator().evaluate(
        _run(),
        events,
        ExpectedBehavior(status=RunStatus.COMPLETED, final_answer_contains="missing"),
        replay=_run(),
    )

    assert success.metrics["task_success"] == 1.0
    assert mismatch.metrics["task_success"] == 0.0
    assert any("final_answer" in failure for failure in mismatch.failures)


def test_recovery_rate_distinguishes_faulted_and_clean_runs() -> None:
    clean = Evaluator().evaluate(
        _run(),
        [_event(1, EventType.RUN_STARTED, {})],
        ExpectedBehavior(status=RunStatus.COMPLETED),
        replay=_run(),
    )
    recovered = Evaluator().evaluate(
        _run(),
        [_event(1, EventType.FAULT_INJECTED, {})],
        ExpectedBehavior(status=RunStatus.COMPLETED, recovered=True),
        replay=_run(),
    )
    unrecovered = Evaluator().evaluate(
        _run(RunStatus.TERMINATED),
        [_event(1, EventType.FAULT_INJECTED, {})],
        ExpectedBehavior(status=RunStatus.TERMINATED, recovered=False),
        replay=_run(RunStatus.TERMINATED),
    )

    assert clean.metrics["recovery_rate"] == 1.0
    assert recovered.metrics["recovery_rate"] == 1.0
    assert recovered.passed is True
    assert unrecovered.metrics["recovery_rate"] == 0.0
    assert unrecovered.passed is True


def test_policy_violation_counts_execution_but_denial_counts_decisions() -> None:
    events = [
        _event(
            1,
            EventType.POLICY_EVALUATED,
            {"call_id": "call-1", "tool_name": "send_message", "decision": "deny"},
        ),
        _event(2, EventType.TOOL_STARTED, {"call_id": "call-1", "tool_name": "send_message"}),
        _event(
            3,
            EventType.POLICY_EVALUATED,
            {"call_id": "call-2", "tool_name": "send_message", "decision": "deny"},
        ),
    ]
    expected = ExpectedBehavior(
        status=RunStatus.COMPLETED,
        max_policy_violations=0,
        min_policy_denials=2,
    )

    result = Evaluator().evaluate(_run(), events, expected, replay=_run())

    assert result.metrics["policy_violation_count"] == 1.0
    assert result.metrics["policy_denial_count"] == 2.0
    assert result.passed is False
    assert any("policy_violation" in failure for failure in result.failures)


def test_loop_termination_metric_reads_run_terminated_reason() -> None:
    result = Evaluator().evaluate(
        _run(RunStatus.TERMINATED),
        [
            _event(
                1,
                EventType.RUN_TERMINATED,
                {"reason": "repeated_tool_call", "steps": 2},
            )
        ],
        ExpectedBehavior(
            status=RunStatus.TERMINATED,
            required_events=[EventType.RUN_TERMINATED],
            expected_termination_reason="repeated_tool_call",
        ),
        replay=_run(RunStatus.TERMINATED),
    )

    assert result.metrics["loop_termination_count"] == 1.0
    assert result.passed is True


def test_aggregate_metrics_use_run_events_and_tool_durations() -> None:
    events = [
        _event(1, EventType.TOOL_REQUESTED, {"call_id": "call-1", "tool_name": "one"}),
        _event(
            2,
            EventType.TOOL_SUCCEEDED,
            {
                "result": {
                    "call_id": "call-1",
                    "tool_name": "one",
                    "success": True,
                    "output": {},
                    "error": None,
                    "duration_ms": 10.0,
                    "metadata": {},
                }
            },
        ),
        _event(3, EventType.TOOL_REQUESTED, {"call_id": "call-2", "tool_name": "two"}),
        _event(
            4,
            EventType.TOOL_FAILED,
            {
                "result": {
                    "call_id": "call-2",
                    "tool_name": "two",
                    "success": False,
                    "output": None,
                    "error": "failed",
                    "duration_ms": 20.0,
                    "metadata": {},
                }
            },
        ),
    ]
    run = _run()

    result = Evaluator().evaluate(
        run,
        events,
        ExpectedBehavior(status=RunStatus.COMPLETED),
        replay=run,
    )

    assert result.metrics["average_steps"] == 2.0
    assert result.metrics["average_tool_calls"] == 2.0
    assert result.metrics["estimated_token_cost"] == 10.0
    assert result.metrics["average_latency_ms"] == 15.0


def test_replay_fidelity_requires_matching_replay_record() -> None:
    run = _run()
    replay = run.model_copy(update={"state_hash": "different"})

    result = Evaluator().evaluate(
        run,
        [],
        ExpectedBehavior(status=RunStatus.COMPLETED),
        replay=replay,
    )

    assert result.metrics["replay_fidelity"] == 0.0
    assert result.passed is False
    assert "replay_mismatch" in result.failures


def test_missing_replay_cannot_award_full_fidelity() -> None:
    result = Evaluator().evaluate(
        _run(),
        [],
        ExpectedBehavior(status=RunStatus.COMPLETED),
    )

    assert result.metrics["replay_fidelity"] == 0.0
    assert result.passed is False
    assert "replay_missing" in result.failures


def test_expected_termination_reason_must_match_persisted_reason() -> None:
    result = Evaluator().evaluate(
        _run(RunStatus.TERMINATED),
        [
            _event(
                1,
                EventType.RUN_TERMINATED,
                {"reason": "token_budget_exceeded", "steps": 2},
            )
        ],
        ExpectedBehavior(
            status=RunStatus.TERMINATED,
            expected_termination_reason="repeated_tool_call",
        ),
        replay=_run(RunStatus.TERMINATED),
    )

    assert result.passed is False
    assert (
        "termination_reason_mismatch:repeated_tool_call!=token_budget_exceeded"
        in result.failures
    )


def test_tool_call_bounds_and_policy_denials_are_enforced() -> None:
    events = [
        _event(1, EventType.TOOL_REQUESTED, {"call_id": "call-1", "tool_name": "one"}),
    ]
    expected = ExpectedBehavior(
        status=RunStatus.COMPLETED,
        min_policy_denials=1,
        min_tool_calls=2,
        max_tool_calls=1,
    )

    result = Evaluator().evaluate(_run(), events, expected, replay=_run())

    assert result.passed is False
    assert any("policy_denial_count" in failure for failure in result.failures)
    assert any("min_tool_calls" in failure for failure in result.failures)


def test_evaluate_suite_returns_aggregate_pass_rate(tmp_path: Path) -> None:
    scenario = Scenario(
        name="unit_suite",
        user_input="finish",
        model_script=[
            ModelResponse(action=FinalAnswer(kind="final", content="done"), token_usage=1)
        ],
        expected=ExpectedBehavior(status=RunStatus.COMPLETED, final_answer_contains="done"),
    )

    summary = evaluate_suite([scenario], tmp_path, seed=42)

    assert summary.total_scenarios == 1
    assert summary.passed_scenarios == 1
    assert summary.failed_scenarios == 0
    assert summary.pass_rate == 1.0
    assert len(summary.results) == 1
    assert summary.results[0].metrics["replay_fidelity"] == 1.0
