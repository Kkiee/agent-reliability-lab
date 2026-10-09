from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentlab.scenario import load_scenario, load_scenarios


def _scenario_payload(name: str = "sample") -> dict[str, object]:
    return {
        "name": name,
        "user_input": "finish",
        "model_script": [
            {
                "action": {"kind": "final", "content": "done"},
                "token_usage": 1,
            }
        ],
        "expected": {"status": "completed"},
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_all_nine_scenarios_load() -> None:
    scenarios = load_scenarios(Path("scenarios"))
    assert {scenario.name for scenario in scenarios} == {
        "happy_path",
        "tool_timeout_recovery",
        "malformed_tool_output",
        "empty_result_fallback",
        "loop_detection",
        "budget_exhaustion",
        "unauthorized_side_effect",
        "prompt_injection",
        "contradictory_evidence",
    }


def test_load_scenario_rejects_unknown_fields(tmp_path: Path) -> None:
    payload = _scenario_payload()
    payload["unexpected"] = True
    path = tmp_path / "unknown.json"
    _write_json(path, payload)

    with pytest.raises(ValueError, match="(?i)(extra|unknown)"):
        load_scenario(path)


def test_load_scenario_reports_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid JSON"):
        load_scenario(path)


def test_load_scenarios_rejects_empty_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no.*scenario"):
        load_scenarios(tmp_path)


def test_load_scenarios_rejects_duplicate_names(tmp_path: Path) -> None:
    _write_json(tmp_path / "first.json", _scenario_payload("duplicate"))
    _write_json(tmp_path / "second.json", _scenario_payload("duplicate"))

    with pytest.raises(ValueError, match="duplicate.*duplicate"):
        load_scenarios(tmp_path)
