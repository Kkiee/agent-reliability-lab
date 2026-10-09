from __future__ import annotations

from pathlib import Path

from agentlab.adapters.fake import FakeAdapter
from agentlab.chaos import ChaosInjector
from agentlab.policy import PolicyEngine
from agentlab.replay import ReplayEngine
from agentlab.reporting import write_run_html_report
from agentlab.runtime import AgentRuntime
from agentlab.scenario import load_scenario
from agentlab.store import FileEventStore
from agentlab.tools.builtin import build_default_registry


def main() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    scenario = load_scenario(repository_root / "examples" / "custom_scenario.json")
    runs_dir = repository_root / "runs" / "quickstart"
    store = FileEventStore(runs_dir)
    run_id = _next_run_id(runs_dir)
    runtime = AgentRuntime(
        adapter=FakeAdapter(scenario.model_script),
        event_sink=store,
        seed=42,
        tools=build_default_registry(),
        policy=PolicyEngine(scenario.policy),
        chaos=ChaosInjector(scenario.faults, seed=42) if scenario.faults else None,
    )
    record = runtime.run(scenario.user_input, run_id=run_id)
    events = store.read_events(record.run_id)
    replay = ReplayEngine(store).replay(record.run_id)
    report_path = write_run_html_report(
        record.run_id,
        store,
        runs_dir / "report.html",
    )

    print(f"status={record.status.value}")
    print(f"event_types={','.join(event.type.value for event in events)}")
    print(f"state_hash={record.state_hash}")
    print("replay_model_calls=0 replay_tool_calls=0")
    print(f"replay_consistent={str(replay.state_hash == record.state_hash).lower()}")
    print(f"report={report_path}")


def _next_run_id(root: Path, base: str = "quickstart") -> str:
    candidate = base
    suffix = 2
    while (root / candidate).exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


if __name__ == "__main__":
    main()
