from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from agentlab import __version__
from agentlab.evaluator import BenchmarkSummary, EvaluationResult
from agentlab.events import Event
from agentlab.models import EventType, RunStatus
from agentlab.replay import ReplayEngine
from agentlab.store import EventIntegrityError, FileEventStore

_FIXTURE_LIMITATION = (
    "这是确定性测试夹具，不代表模型综合能力。"
    " Metrics come from scripted fixtures and local fault injection, not a general model benchmark."
)
_TEMPLATE_DIR = Path(__file__).with_name("templates")
_TEMPLATE_NAME = "report.html.j2"


def write_benchmark_json_report(summary: BenchmarkSummary, path: Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = _benchmark_payload(summary)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def write_benchmark_html_report(summary: BenchmarkSummary, path: Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    context = _benchmark_payload(summary)
    context["kind"] = "benchmark"
    output.write_text(_render("Benchmark report", context), encoding="utf-8")
    return output


def write_run_html_report(run_id: str, store: FileEventStore, path: Path) -> Path:
    state = store.load_state(run_id)
    events = store.read_events(run_id)
    manifest_metadata = store.load_manifest_metadata(run_id)
    seed = manifest_metadata.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise EventIntegrityError("run manifest seed must be an integer")
    persisted_hash = store.load_state_hash(run_id)
    replay_consistent = False
    replay_hash: str | None = None
    replay_error: str | None = None
    try:
        replay = ReplayEngine(store).replay(run_id)
    except EventIntegrityError as exc:
        replay_error = str(exc)
    else:
        replay_hash = replay.state_hash
        replay_consistent = replay.state_hash == persisted_hash

    fault_injections = _event_count(events, EventType.FAULT_INJECTED)
    recoveries = int(fault_injections > 0 and state.status == RunStatus.COMPLETED)
    policy_denials = sum(
        1
        for event in events
        if event.type == EventType.POLICY_EVALUATED
        and event.payload.get("decision") == "deny"
    )
    context: dict[str, Any] = {
        "kind": "run",
        "project_version": __version__,
        "generated_at": _generated_at(),
        "seed": seed,
        "run_id": run_id,
        "status": state.status.value,
        "steps": state.step,
        "tool_calls": state.tool_calls,
        "token_usage": state.token_usage,
        "state_hash": persisted_hash,
        "replay_hash": replay_hash,
        "replay_consistent": replay_consistent,
        "replay_error": replay_error,
        "fault_injections": fault_injections,
        "recoveries": recoveries,
        "policy_denials": policy_denials,
        "limitations": _FIXTURE_LIMITATION,
    }
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_render(f"Run report: {run_id}", context), encoding="utf-8")
    return output


def _benchmark_payload(summary: BenchmarkSummary) -> dict[str, Any]:
    results = [_result_payload(result) for result in summary.results]
    total_scenarios = summary.total_scenarios
    replay_consistent = sum(
        result.metrics.get("replay_fidelity", 0.0) == 1.0 for result in summary.results
    )
    return {
        "schema_version": 1,
        "project_version": __version__,
        "generated_at": _generated_at(),
        "seed": summary.seed,
        "total_scenarios": total_scenarios,
        "passed_scenarios": summary.passed_scenarios,
        "failed_scenarios": summary.failed_scenarios,
        "pass_rate": summary.pass_rate,
        "pass_rate_percent": f"{summary.pass_rate * 100:.2f}%",
        "fault_injections": _metric_total(summary, "fault_injection_count"),
        "recoveries": _metric_total(summary, "recovery_count"),
        "policy_denials": _metric_total(summary, "policy_denial_count"),
        "replay_consistency_percent": (
            f"{(replay_consistent / total_scenarios * 100):.2f}%" if total_scenarios else "0.00%"
        ),
        "replay_consistent_scenarios": replay_consistent,
        "results": results,
        "limitations": _FIXTURE_LIMITATION,
    }


def _result_payload(result: EvaluationResult) -> dict[str, Any]:
    metrics = {
        name: value
        for name, value in result.metrics.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    return {
        "scenario_name": result.scenario_name,
        "run_id": result.run_id,
        "status": result.status.value,
        "passed": result.passed,
        "metrics": metrics,
        "metric_items": [
            {"name": _metric_label(name), "value": _format_metric(value)}
            for name, value in metrics.items()
        ],
        "failures": result.failures,
        "report_path": result.report_path,
    }


def _metric_total(summary: BenchmarkSummary, metric_name: str) -> int:
    return int(sum(result.metrics.get(metric_name, 0.0) for result in summary.results))


def _event_count(events: list[Event], event_type: EventType) -> int:
    return sum(event.type == event_type for event in events)


def _metric_label(name: str) -> str:
    return name.replace("_", " ").title()


def _format_metric(value: float | int) -> str:
    numeric = float(value)
    return f"{numeric:.2f}"


def _generated_at() -> str:
    return datetime.now(UTC).isoformat()


def _render(title: str, context: dict[str, Any]) -> str:
    environment = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = environment.get_template(_TEMPLATE_NAME)
    return template.render(title=title, **context)
