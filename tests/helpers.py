from __future__ import annotations

from pathlib import Path

from agentlab.adapters.fake import FakeAdapter
from agentlab.chaos import ChaosInjector
from agentlab.evaluator import EvaluationResult, Evaluator
from agentlab.models import Scenario
from agentlab.policy import PolicyEngine
from agentlab.replay import ReplayEngine
from agentlab.runtime import AgentRuntime
from agentlab.store import FileEventStore
from agentlab.tools.builtin import build_default_registry


def run_scenario(scenario: Scenario, runs_dir: Path, seed: int = 42) -> EvaluationResult:
    store = FileEventStore(runs_dir)
    runtime = AgentRuntime(
        adapter=FakeAdapter(scenario.model_script),
        event_sink=store,
        seed=seed,
        tools=build_default_registry(),
        policy=PolicyEngine(scenario.policy),
        chaos=ChaosInjector(scenario.faults, seed=seed),
    )
    record = runtime.run(scenario.user_input, run_id=f"test-{scenario.name}")
    events = store.read_events(record.run_id)
    replay = ReplayEngine(store).replay(record.run_id)
    return Evaluator().evaluate(
        record,
        events,
        scenario.expected,
        replay=replay,
        scenario_name=scenario.name,
    )