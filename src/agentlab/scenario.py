from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from agentlab.models import Scenario


class ScenarioLoadError(ValueError):
    pass


class DuplicateScenarioError(ScenarioLoadError):
    pass


def load_scenario(path: Path) -> Scenario:
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ScenarioLoadError(f"invalid UTF-8 in scenario file {path}: {exc}") from exc
    except OSError as exc:
        raise ScenarioLoadError(f"cannot read scenario file {path}: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ScenarioLoadError(f"invalid JSON in scenario file {path}: {exc}") from exc

    try:
        return Scenario.model_validate(payload)
    except ValidationError as exc:
        raise ScenarioLoadError(f"invalid scenario file {path}: {exc}") from exc


def load_scenarios(directory: Path = Path("scenarios")) -> list[Scenario]:
    if not directory.is_dir():
        raise ScenarioLoadError(f"scenario directory does not exist: {directory}")

    paths = sorted(path for path in directory.glob("*.json") if path.is_file())
    if not paths:
        raise ScenarioLoadError(f"no scenario JSON files found in directory: {directory}")

    scenarios: list[Scenario] = []
    names: set[str] = set()
    for path in paths:
        scenario = load_scenario(path)
        if scenario.name in names:
            raise DuplicateScenarioError(f"duplicate scenario name: {scenario.name}")
        names.add(scenario.name)
        scenarios.append(scenario)
    return scenarios
