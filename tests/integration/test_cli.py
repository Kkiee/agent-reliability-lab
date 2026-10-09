from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from agentlab.cli import app


def test_list_scenarios_command() -> None:
    result = CliRunner().invoke(app, ["list-scenarios"])

    assert result.exit_code == 0
    assert "happy_path" in result.stdout
    assert "tool_timeout_recovery" in result.stdout


def test_bench_returns_nonzero_when_threshold_fails(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["bench", "scenarios", "--runs-dir", str(tmp_path), "--fail-under", "1.01"],
    )

    assert result.exit_code == 1
    assert (tmp_path / "report.json").is_file()
    assert (tmp_path / "report.html").is_file()


def test_run_replay_and_report_commands(tmp_path: Path) -> None:
    runner = CliRunner()
    run_result = runner.invoke(
        app,
        ["run", "happy_path", "--seed", "42", "--runs-dir", str(tmp_path)],
    )

    assert run_result.exit_code == 0, run_result.output
    run_dirs = [path for path in tmp_path.iterdir() if path.is_dir()]
    assert len(run_dirs) == 1
    run_id = run_dirs[0].name

    replay_result = runner.invoke(app, ["replay", run_id, "--runs-dir", str(tmp_path)])
    assert replay_result.exit_code == 0
    assert "state_hash=" in replay_result.stdout
    assert "model_calls=0 tool_calls=0" in replay_result.stdout

    report_result = runner.invoke(app, ["report", run_id, "--runs-dir", str(tmp_path)])
    assert report_result.exit_code == 0
    assert (run_dirs[0] / "report.html").is_file()


def test_demo_runs_only_two_scenarios_and_writes_html(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["demo"])

    assert result.exit_code == 0, result.output
    report = tmp_path / "runs" / "demo" / "report.html"
    assert report.is_file()
    html = report.read_text(encoding="utf-8")
    assert "happy_path" in html
    assert "tool_timeout_recovery" in html
    assert "loop_detection" not in html


def test_cli_errors_do_not_print_tracebacks(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["run", "does-not-exist", "--runs-dir", str(tmp_path)],
    )

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "Error:" in result.output


def test_report_command_does_not_expose_no_html(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["report", "missing-run", "--runs-dir", str(tmp_path), "--no-html"],
    )

    assert result.exit_code != 0
    assert "No such option" in result.output
