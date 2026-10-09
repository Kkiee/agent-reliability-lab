from __future__ import annotations

from pathlib import Path

import pytest

from agentlab.scenario import load_scenarios
from tests.helpers import run_scenario


@pytest.mark.parametrize(
    "scenario",
    load_scenarios(Path("scenarios")),
    ids=lambda scenario: scenario.name,
)
def test_scenario_meets_expected_behavior(scenario, tmp_path: Path) -> None:
    result = run_scenario(scenario, runs_dir=tmp_path)

    assert result.passed, result.failures
    assert result.metrics["replay_fidelity"] == 1.0
    assert result.metrics["policy_violation_count"] == 0.0
    assert result.metrics["trace_completeness"] == 1.0