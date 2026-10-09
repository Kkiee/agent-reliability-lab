from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pydantic import Field

from agentlab.adapters.fake import FakeAdapter
from agentlab.chaos import ChaosInjector
from agentlab.events import Event
from agentlab.models import (
    EventType,
    ExpectedBehavior,
    RunRecord,
    RunStatus,
    Scenario,
    StrictModel,
)
from agentlab.policy import PolicyEngine
from agentlab.replay import ReplayEngine
from agentlab.runtime import AgentRuntime
from agentlab.store import FileEventStore
from agentlab.tools.builtin import build_default_registry


class EvaluationResult(StrictModel):
    scenario_name: str
    run_id: str
    passed: bool
    metrics: dict[str, float]
    failures: list[str]
    report_path: str | None = None


class BenchmarkSummary(StrictModel):
    total_scenarios: int = Field(default=0, ge=0)
    passed_scenarios: int = Field(default=0, ge=0)
    failed_scenarios: int = Field(default=0, ge=0)
    pass_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    results: list[EvaluationResult] = Field(default_factory=list)
    seed: int = 42
    report_path: str | None = None

    @property
    def scenario_count(self) -> int:
        return self.total_scenarios

    @property
    def passed_count(self) -> int:
        return self.passed_scenarios

    @property
    def failed_count(self) -> int:
        return self.failed_scenarios

    @property
    def total(self) -> int:
        return self.total_scenarios

    @property
    def passed(self) -> int:
        return self.passed_scenarios

    @property
    def failed(self) -> int:
        return self.failed_scenarios


class Evaluator:
    def evaluate(
        self,
        run: RunRecord,
        events: list[Event],
        expected: ExpectedBehavior,
        replay: RunRecord | None = None,
        report_path: str | None = None,
        scenario_name: str | None = None,
    ) -> EvaluationResult:
        event_types = [event.type for event in events]
        event_type_set = set(event_types)
        tool_call_count = sum(event.type == EventType.TOOL_REQUESTED for event in events)
        policy_denial_count = sum(
            event.type == EventType.POLICY_EVALUATED
            and event.payload.get("decision") == "deny"
            for event in events
        )
        policy_violation_count = _policy_violation_count(events)
        fault_injected = EventType.FAULT_INJECTED in event_type_set
        recovered = fault_injected and run.status == RunStatus.COMPLETED
        recovery_rate = 1.0 if not fault_injected else float(recovered)
        loop_termination_count = float(_termination_reason(events) == "repeated_tool_call")
        trace_completeness = float(
            all(event_type in event_type_set for event_type in expected.required_events)
        )
        replay_fidelity = 1.0
        if replay is not None and replay.state_hash != run.state_hash:
            replay_fidelity = 0.0

        status_matches = run.status == expected.status
        final_answer_matches = _final_answer_matches(run.final_answer, expected)
        task_success = float(status_matches and final_answer_matches)

        failures: list[str] = []
        if not status_matches:
            failures.append(
                f"status_mismatch: expected {expected.status.value}, got {run.status.value}"
            )
        if not final_answer_matches:
            if run.final_answer is None:
                failures.append("final_answer_missing")
            else:
                failures.append(
                    f"final_answer_mismatch:{expected.final_answer_contains}"
                )
        if expected.recovered is not None and expected.recovered != recovered:
            failures.append(f"recovery_mismatch: expected {expected.recovered}, got {recovered}")
        if policy_violation_count > expected.max_policy_violations:
            failures.append(
                "policy_violation_count:"
                f"{policy_violation_count}>{expected.max_policy_violations}"
            )
        if policy_denial_count < expected.min_policy_denials:
            failures.append(
                f"policy_denial_count:{policy_denial_count}<{expected.min_policy_denials}"
            )
        for required_event in expected.required_events:
            if required_event not in event_type_set:
                failures.append(f"missing_required_event:{required_event.value}")
        if tool_call_count < expected.min_tool_calls:
            failures.append(f"min_tool_calls:{tool_call_count}<{expected.min_tool_calls}")
        if expected.max_tool_calls is not None and tool_call_count > expected.max_tool_calls:
            failures.append(f"max_tool_calls:{tool_call_count}>{expected.max_tool_calls}")
        if replay_fidelity != 1.0:
            failures.append("replay_mismatch")

        return EvaluationResult(
            scenario_name=scenario_name or run.run_id,
            run_id=run.run_id,
            passed=not failures,
            metrics={
                "task_success": task_success,
                "recovery_rate": recovery_rate,
                "policy_violation_count": float(policy_violation_count),
                "policy_denial_count": float(policy_denial_count),
                "loop_termination_count": loop_termination_count,
                "average_steps": float(run.steps),
                "average_tool_calls": float(tool_call_count),
                "estimated_token_cost": float(run.token_usage),
                "average_latency_ms": _average_latency_ms(events),
                "replay_fidelity": replay_fidelity,
                "trace_completeness": trace_completeness,
            },
            failures=failures,
            report_path=report_path,
        )


def evaluate_suite(
    scenarios: Sequence[Scenario],
    runs_dir: Path,
    seed: int = 42,
) -> BenchmarkSummary:
    results = [
        _evaluate_scenario(scenario, runs_dir=runs_dir, seed=seed)
        for scenario in scenarios
    ]
    passed_scenarios = sum(result.passed for result in results)
    total_scenarios = len(results)
    return BenchmarkSummary(
        total_scenarios=total_scenarios,
        passed_scenarios=passed_scenarios,
        failed_scenarios=total_scenarios - passed_scenarios,
        pass_rate=(passed_scenarios / total_scenarios if total_scenarios else 0.0),
        results=results,
        seed=seed,
    )


def _evaluate_scenario(scenario: Scenario, runs_dir: Path, seed: int) -> EvaluationResult:
    store = FileEventStore(runs_dir)
    runtime = AgentRuntime(
        adapter=FakeAdapter(scenario.model_script),
        event_sink=store,
        seed=seed,
        tools=build_default_registry(),
        policy=PolicyEngine(scenario.policy),
        chaos=ChaosInjector(scenario.faults, seed=seed),
    )
    record = runtime.run(scenario.user_input, run_id=f"benchmark-{scenario.name}")
    events = store.read_events(record.run_id)
    replay = ReplayEngine(store).replay(record.run_id)
    return Evaluator().evaluate(
        record, events, scenario.expected, replay=replay, scenario_name=scenario.name
    )


def _final_answer_matches(final_answer: str | None, expected: ExpectedBehavior) -> bool:
    if expected.final_answer_contains is None:
        return True
    return final_answer is not None and expected.final_answer_contains in final_answer


def _policy_violation_count(events: list[Event]) -> int:
    denied_call_ids = {
        call_id
        for event in events
        if event.type == EventType.POLICY_EVALUATED
        and event.payload.get("decision") == "deny"
        if isinstance((call_id := event.payload.get("call_id")), str)
    }
    started_call_ids = {
        call_id
        for event in events
        if event.type == EventType.TOOL_STARTED
        if isinstance((call_id := event.payload.get("call_id")), str)
    }
    return len(denied_call_ids & started_call_ids)


def _termination_reason(events: list[Event]) -> str | None:
    for event in events:
        if event.type == EventType.RUN_TERMINATED:
            reason = event.payload.get("reason")
            if isinstance(reason, str):
                return reason
    return None


def _average_latency_ms(events: list[Event]) -> float:
    durations: list[float] = []
    for event in events:
        if event.type not in {EventType.TOOL_SUCCEEDED, EventType.TOOL_FAILED}:
            continue
        result = event.payload.get("result")
        if not isinstance(result, dict):
            continue
        duration = result.get("duration_ms")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            continue
        durations.append(float(duration))
    return sum(durations) / len(durations) if durations else 0.0