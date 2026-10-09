from __future__ import annotations

import json
from pathlib import Path

from agentlab.evaluator import BenchmarkSummary, EvaluationResult
from agentlab.models import RunStatus
from agentlab.reporting import (
    write_benchmark_html_report,
    write_benchmark_json_report,
    write_run_html_report,
)
from agentlab.scenario import load_scenario
from agentlab.store import FileEventStore
from tests.helpers import run_scenario


def _result(index: int) -> EvaluationResult:
    return EvaluationResult(
        scenario_name=f"scenario_{index}",
        run_id=f"run-{index}",
        status=RunStatus.COMPLETED,
        passed=True,
        metrics={
            "task_success": 1.0,
            "recovery_rate": 1.0,
            "fault_injection_count": 1.0,
            "recovery_count": 1.0,
            "policy_violation_count": 0.0,
            "policy_denial_count": 1.0,
            "loop_termination_count": 0.0,
            "average_steps": 2.0,
            "average_tool_calls": 1.0,
            "estimated_token_cost": 12.0,
            "average_latency_ms": 4.0,
            "replay_fidelity": 1.0,
            "trace_completeness": 1.0,
        },
        failures=[],
    )


def _summary() -> BenchmarkSummary:
    return BenchmarkSummary(
        total_scenarios=9,
        passed_scenarios=9,
        failed_scenarios=0,
        pass_rate=1.0,
        results=[_result(index) for index in range(9)],
        seed=42,
    )


def test_html_report_contains_real_metrics(tmp_path: Path) -> None:
    path = write_benchmark_html_report(_summary(), tmp_path / "report.html")
    html = path.read_text(encoding="utf-8")

    assert "9 scenarios" in html
    assert "Completed 9" in html
    assert "100.00%" in html
    assert "run-0" in html
    assert "completed" in html
    assert "Fault injections" in html
    assert "Recoveries" in html
    assert "Policy denials" in html
    assert "Replay consistency" in html
    assert "0.1.0" in html
    assert "seed 42" in html
    assert "这是确定性测试夹具，不代表模型综合能力" in html
    assert "cdn." not in html
    assert "<script src=" not in html
    assert "http://" not in html
    assert "https://" not in html


def test_benchmark_json_report_round_trips_real_metrics(tmp_path: Path) -> None:
    path = write_benchmark_json_report(_summary(), tmp_path / "report.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["project_version"] == "0.1.0"
    assert payload["seed"] == 42
    assert payload["total_scenarios"] == 9
    assert payload["passed_scenarios"] == 9
    assert payload["pass_rate"] == 1.0
    assert payload["results"][0]["run_id"] == "run-0"
    assert payload["results"][0]["metrics"]["replay_fidelity"] == 1.0
    assert "这是确定性测试夹具，不代表模型综合能力" in payload["limitations"]
    assert "generated_at" in payload


def test_run_html_report_uses_persisted_run_facts(tmp_path: Path) -> None:
    scenario_path = Path(__file__).resolve().parents[2] / "scenarios" / "happy_path.json"
    result = run_scenario(load_scenario(scenario_path), runs_dir=tmp_path)
    store = FileEventStore(tmp_path)

    path = write_run_html_report(result.run_id, store, tmp_path / "run-report.html")
    html = path.read_text(encoding="utf-8")

    assert result.run_id in html
    assert "completed" in html
    assert "Replay consistent" in html
    assert "Model calls" in html
    assert "cdn." not in html
    assert "https://" not in html


def test_benchmark_html_escapes_untrusted_text(tmp_path: Path) -> None:
    result = EvaluationResult(
        scenario_name='<img src=x onerror="alert(1)">',
        run_id="run-<b>id</b>",
        status=RunStatus.FAILED,
        passed=False,
        metrics={"task_success": 0.0, "replay_fidelity": 1.0},
        failures=["<script>alert(1)</script>"],
    )
    summary = BenchmarkSummary(
        total_scenarios=1,
        passed_scenarios=0,
        failed_scenarios=1,
        pass_rate=0.0,
        results=[result],
        seed=42,
    )

    path = write_benchmark_html_report(summary, tmp_path / "escaped.html")
    html = path.read_text(encoding="utf-8")

    assert "&lt;img src=x onerror=" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img src=x" not in html
    assert "<script>alert(1)</script>" not in html


def test_run_html_report_uses_persisted_seed(tmp_path: Path) -> None:
    scenario_path = Path(__file__).resolve().parents[2] / "scenarios" / "happy_path.json"
    result = run_scenario(
        load_scenario(scenario_path),
        runs_dir=tmp_path,
        seed=9876,
        run_id_prefix="seed-run",
    )
    store = FileEventStore(tmp_path)

    path = write_run_html_report(result.run_id, store, tmp_path / "seed-report.html")
    html = path.read_text(encoding="utf-8")

    assert "seed 9876" in html
    assert "from run manifest" not in html
