from __future__ import annotations

from pathlib import Path

import pytest

from agentlab.scenario import load_scenarios
from tests.helpers import run_scenario

SCENARIOS_DIR = Path(__file__).resolve().parents[2] / "scenarios"


@pytest.mark.parametrize(
    "scenario",
    load_scenarios(SCENARIOS_DIR),
    ids=lambda scenario: scenario.name,
)
def test_scenario_meets_expected_behavior(scenario, tmp_path: Path) -> None:
    result = run_scenario(scenario, runs_dir=tmp_path)

    assert result.passed, result.failures
    assert result.metrics["replay_fidelity"] == 1.0
    assert result.metrics["policy_violation_count"] == 0.0
    assert result.metrics["trace_completeness"] == 1.0


@pytest.mark.parametrize(
    ("scenario_name", "termination_reason"),
    [
        ("loop_detection", "repeated_tool_call"),
        ("budget_exhaustion", "token_budget_exceeded"),
    ],
)
def test_termination_scenarios_match_expected_reason(
    scenario_name: str,
    termination_reason: str,
    tmp_path: Path,
) -> None:
    scenarios = {scenario.name: scenario for scenario in load_scenarios(SCENARIOS_DIR)}
    scenario = scenarios[scenario_name]
    result = run_scenario(scenario, runs_dir=tmp_path)

    assert scenario.expected.expected_termination_reason == termination_reason
    assert result.passed, result.failures
    assert result.metrics["replay_fidelity"] == 1.0


def test_loop_detection_reports_loop_termination_metric(tmp_path: Path) -> None:
    scenarios = {scenario.name: scenario for scenario in load_scenarios(SCENARIOS_DIR)}

    result = run_scenario(scenarios["loop_detection"], runs_dir=tmp_path)

    assert result.passed, result.failures
    assert result.metrics["loop_termination_count"] == 1.0
