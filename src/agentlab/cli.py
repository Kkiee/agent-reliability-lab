from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from agentlab.adapters.base import ModelAdapter
from agentlab.adapters.fake import FakeAdapter
from agentlab.adapters.openai_compatible import OpenAICompatibleAdapter
from agentlab.chaos import ChaosInjector
from agentlab.evaluator import BenchmarkSummary, EvaluationResult, Evaluator, evaluate_suite
from agentlab.models import Scenario
from agentlab.policy import PolicyEngine
from agentlab.replay import ReplayEngine
from agentlab.reporting import (
    write_benchmark_html_report,
    write_benchmark_json_report,
    write_run_html_report,
)
from agentlab.runtime import AgentRuntime
from agentlab.scenario import load_scenario, load_scenarios
from agentlab.store import FileEventStore
from agentlab.tools.builtin import build_default_registry

app = typer.Typer(
    name="agentlab",
    help="Deterministic reliability tests, replay, and reports for tool-using agents.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)


@app.command("list-scenarios")
def list_scenarios_command(
    scenarios_dir: Annotated[
        Path,
        typer.Option("--scenarios-dir", help="Directory containing scenario JSON files."),
    ] = Path("scenarios"),
) -> None:
    def action() -> None:
        directory = _scenario_directory(scenarios_dir)
        for scenario in load_scenarios(directory):
            description = f" - {scenario.description}" if scenario.description else ""
            typer.echo(f"{scenario.name}{description}")

    _guard(action)


@app.command("run")
def run_command(
    scenario: Annotated[str, typer.Argument(help="Scenario name or path.")],
    seed: Annotated[int, typer.Option("--seed", help="Deterministic run seed.")] = 42,
    adapter: Annotated[str, typer.Option("--adapter", help="fake or openai-compatible.")] = "fake",
    runs_dir: Annotated[
        Path,
        typer.Option("--runs-dir", "--out", help="Directory for saved runs."),
    ] = Path("runs"),
) -> None:
    def action() -> None:
        selected = _load_scenario_spec(scenario)
        store = FileEventStore(runs_dir)
        run_id = _next_run_id(store.root, f"run-{selected.name}")
        model_adapter = _build_adapter(adapter, selected)
        result = _execute_run(selected, store, model_adapter, run_id, seed)
        if result.passed:
            typer.echo(f"run_id={result.run_id} status={result.status.value} passed=true")
        else:
            typer.echo(
                f"run_id={result.run_id} status={result.status.value} passed=false "
                f"failures={'; '.join(result.failures)}"
            )

    _guard(action)


@app.command("replay")
def replay_command(
    run_id: Annotated[str, typer.Argument(help="Saved run id.")],
    runs_dir: Annotated[Path, typer.Option("--runs-dir", help="Directory for saved runs.")] = Path(
        "runs"
    ),
) -> None:
    def action() -> None:
        replay = ReplayEngine(runs_dir).replay(run_id)
        typer.echo(f"state_hash={replay.state_hash}")
        typer.echo(f"status={replay.status.value}")
        typer.echo("model_calls=0 tool_calls=0")

    _guard(action)


@app.command("report")
def report_command(
    run_id: Annotated[str, typer.Argument(help="Saved run id.")],
    runs_dir: Annotated[Path, typer.Option("--runs-dir", help="Directory for saved runs.")] = Path(
        "runs"
    ),
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional output path."),
    ] = None,
) -> None:
    def action() -> None:
        destination = output or runs_dir / run_id / "report.html"
        report_path = write_run_html_report(run_id, FileEventStore(runs_dir), destination)
        typer.echo(str(report_path))

    _guard(action)


@app.command("bench")
def bench_command(
    scenario_dir: Annotated[str, typer.Argument(help="Directory containing scenario JSON files.")],
    runs_dir: Annotated[
        Path,
        typer.Option("--runs-dir", help="Directory for saved benchmark runs."),
    ] = Path("runs"),
    fail_under: Annotated[
        float,
        typer.Option("--fail-under", help="Minimum acceptable pass rate."),
    ] = 0.80,
    seed: Annotated[int, typer.Option("--seed", help="Deterministic run seed.")] = 42,
) -> None:
    def action() -> None:
        directory = _scenario_directory(Path(scenario_dir))
        scenarios = load_scenarios(directory)
        runs_dir.mkdir(parents=True, exist_ok=True)
        prefix = _next_benchmark_prefix(runs_dir)
        summary = evaluate_suite(scenarios, runs_dir=runs_dir, seed=seed, run_id_prefix=prefix)
        json_path = write_benchmark_json_report(summary, runs_dir / "report.json")
        html_path = write_benchmark_html_report(summary, runs_dir / "report.html")
        typer.echo(
            f"scenarios={summary.total_scenarios} passed={summary.passed_scenarios} "
            f"failed={summary.failed_scenarios} pass_rate={summary.pass_rate:.2f}"
        )
        typer.echo(f"report={html_path}")
        if summary.pass_rate < fail_under:
            typer.echo(
                f"Error: pass rate {summary.pass_rate:.4f} is below threshold {fail_under:.4f}",
                err=True,
            )
            raise typer.Exit(1)
        _ = json_path

    _guard(action)


@app.command("demo")
def demo_command() -> None:
    def action() -> None:
        scenario_directory = _scenario_directory(Path("scenarios"))
        scenarios = {scenario.name: scenario for scenario in load_scenarios(scenario_directory)}
        selected_names = ("happy_path", "tool_timeout_recovery")
        missing = [name for name in selected_names if name not in scenarios]
        if missing:
            raise ValueError(f"demo scenarios are missing: {', '.join(missing)}")
        selected = [scenarios[name] for name in selected_names]
        runs_dir = Path("runs") / "demo"
        runs_dir.mkdir(parents=True, exist_ok=True)
        summary = evaluate_suite(
            selected,
            runs_dir=runs_dir,
            seed=42,
            run_id_prefix=_next_benchmark_prefix(runs_dir, base="demo"),
        )
        report_path = write_benchmark_html_report(summary, runs_dir / "report.html")
        write_benchmark_json_report(summary, runs_dir / "report.json")
        typer.echo(
            f"demo scenarios={summary.total_scenarios} passed={summary.passed_scenarios} "
            f"pass_rate={summary.pass_rate:.2f}"
        )
        typer.echo(f"report={report_path}")

    _guard(action)


def _guard(action: Callable[[], None]) -> None:
    try:
        action()
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None


def _execute_run(
    scenario: Scenario,
    store: FileEventStore,
    adapter: ModelAdapter,
    run_id: str,
    seed: int,
) -> EvaluationResult:
    runtime = AgentRuntime(
        adapter=adapter,
        event_sink=store,
        seed=seed,
        tools=build_default_registry(),
        policy=PolicyEngine(scenario.policy),
        chaos=ChaosInjector(scenario.faults, seed=seed) if scenario.faults else None,
    )
    try:
        record = runtime.run(scenario.user_input, run_id=run_id)
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()
    events = store.read_events(run_id)
    replay = ReplayEngine(store).replay(run_id)
    result = Evaluator().evaluate(
        record,
        events,
        scenario.expected,
        replay=replay,
        scenario_name=scenario.name,
        report_path=str(store.root / run_id / "report.html"),
    )
    run_report = BenchmarkSummary(
        total_scenarios=1,
        passed_scenarios=1 if result.passed else 0,
        failed_scenarios=0 if result.passed else 1,
        pass_rate=1.0 if result.passed else 0.0,
        results=[result],
        seed=seed,
    )
    write_benchmark_json_report(run_report, store.root / run_id / "report.json")
    write_run_html_report(run_id, store, store.root / run_id / "report.html")
    return result


def _build_adapter(name: str, scenario: Scenario) -> ModelAdapter:
    normalized = name.lower().replace("_", "-")
    if normalized == "fake":
        return FakeAdapter(scenario.model_script)
    if normalized in {"openai", "openai-compatible"}:
        return OpenAICompatibleAdapter()
    raise ValueError(f"unknown adapter: {name}")


def _load_scenario_spec(spec: str) -> Scenario:
    path = Path(spec)
    if path.is_file():
        return load_scenario(path)
    scenarios = load_scenarios(_scenario_directory(Path("scenarios")))
    for scenario in scenarios:
        if scenario.name == spec:
            return scenario
    raise ValueError(f"scenario not found: {spec}")


def _scenario_directory(requested: Path) -> Path:
    if requested.is_dir():
        return requested
    if requested == Path("scenarios"):
        package_relative = Path(__file__).resolve().parents[2] / "scenarios"
        if package_relative.is_dir():
            return package_relative
    raise ValueError(f"scenario directory does not exist: {requested}")


def _next_run_id(root: Path, base: str) -> str:
    candidate = base
    suffix = 2
    while (root / candidate).exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _next_benchmark_prefix(root: Path, base: str = "benchmark") -> str:
    candidate = base
    suffix = 2
    while any(root.glob(f"{candidate}-*")):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


if __name__ == "__main__":
    app()
