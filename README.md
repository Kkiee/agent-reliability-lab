# Agent Reliability Lab

Agent Reliability Lab is a local Python toolkit for testing tool-using agents with deterministic replay, policy checks, fault injection, and fixture-based benchmarks.

## Why This Exists

Tool-using agents fail in ways that final-answer tests often miss: a tool times out, a retry loops forever, a side-effecting call bypasses policy, or a model follows an instruction embedded in tool output. These failures are hard to debug when the only record is the final response.

This repository provides a small runtime and a reproducible test harness for those failure modes. The default benchmark uses scripted `FakeAdapter` responses, so it runs offline and does not claim to measure the quality of a real model.

## Current Scope

The `v0.1.0` implementation includes:

- A synchronous `AgentRuntime` that alternates between model responses and tool calls.
- A Pydantic 2 event model, append-only JSONL event store, SHA-256 hash chains, and state snapshots.
- A deterministic `FakeAdapter` plus an optional OpenAI Chat Completions-compatible adapter.
- A policy engine with step, tool-call, token, allow/block list, repeated-call, side-effect, and approval checks.
- Mock tools: `search_docs`, `fetch_record`, `calculate`, and `send_message`. `send_message` only records data in memory.
- Deterministic fault injection for timeout, tool error, malformed JSON, empty result, duplicate result, extra latency metadata, prompt injection, and contradictory evidence.
- Replay from persisted events without calling model adapters or tools.
- Nine local benchmark scenarios, JSON/HTML reports, and a Typer CLI.

The benchmark is a reliability fixture suite, not a general model benchmark. The runtime is not described here as production-ready.

## Architecture

```text
CLI / Python API
        |
        v
+---------------------+       +----------------------+
| AgentRuntime        |<----->| PolicyEngine         |
| state transitions   |       | budgets and allowlist|
+----------+----------+       +----------------------+
           |
           +-----> ModelAdapter
           |       FakeAdapter (default) or OpenAICompatibleAdapter
           |
           +-----> ToolRegistry
           |       validated Pydantic inputs and mock handlers
           |
           +-----> ChaosInjector
           |       deterministic faults keyed by tool and call index
           |
           +-----> EventSink
                   JSONL events + terminal state snapshot
                          |
                          v
                    ReplayEngine
                    state reconstruction with no model/tool calls
```

The event log is the source of truth. `state.json` is a hash-checked snapshot of the reconstructed runtime state; replay first validates the event chain and then compares the reconstructed state hash with the saved snapshot.

More detail is in [docs/architecture.md](docs/architecture.md).

## Quick Start

Run these commands from a fresh clone with Python 3.11 or newer.

```bash
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# POSIX shell
# source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

agentlab list-scenarios
agentlab demo
agentlab bench scenarios --runs-dir runs --fail-under 0.80
python examples/quickstart.py
```

`agentlab demo` runs the happy-path and timeout-recovery fixtures and writes `runs/demo/report.json` and `runs/demo/report.html`. Both report formats are self-contained and do not load remote assets.

## Benchmark Scenarios

The repository contains nine scripted scenarios:

| Scenario | What it exercises |
| --- | --- |
| `happy_path` | An allowed tool call followed by a final answer. |
| `tool_timeout_recovery` | A timeout fault followed by a successful retry. |
| `malformed_tool_output` | A malformed JSON result followed by a clean retry. |
| `empty_result_fallback` | An empty search result followed by a fallback lookup. |
| `loop_detection` | Repeated identical calls terminate the run. |
| `budget_exhaustion` | Token usage above the configured budget terminates the run. |
| `unauthorized_side_effect` | `send_message` is denied before the handler runs. |
| `prompt_injection` | Untrusted text is returned to the model without expanding permissions. |
| `contradictory_evidence` | Conflicting records are reported as uncertain instead of being silently merged. |

## Benchmark Results

The result below is the actual output from the local quality-gate run, not a projected or synthetic metric:

```text
$ agentlab bench scenarios --runs-dir runs --fail-under 0.80
scenarios=9 passed=9 failed=0 pass_rate=1.00
report=runs\report.html
```

The run was captured on 2026-10-09 with Python 3.14.3 and the default seed `42`. Ruff passed, mypy passed, the test suite passed with coverage above the required threshold, and all nine fixture scenarios passed. The pass rate reflects these scripted fixtures only; it is not a ranking of model capability and should not be compared with public model benchmarks.

## Replay Example

Run the happy-path scenario into a fresh directory and replay the saved run:

```text
$ agentlab run happy_path --runs-dir runs/replay-demo
run_id=run-happy_path status=completed passed=true

$ agentlab replay run-happy_path --runs-dir runs/replay-demo
state_hash=05d33b3205b6d598472eca9ff7497bf834cbcd442310553d7cdab4466919dafe
status=completed
model_calls=0 tool_calls=0
```

Replay validates the event hash chain and reconstructs state from event payloads. It does not call the adapter or tool handler, so replaying a run cannot repeat a tool side effect.

## Policies and Fault Injection

Policies are evaluated before a tool handler runs. Budget failures terminate the run; blocked or unauthorized calls are returned to the model as failed tool results so the model can choose another path.

```json
{
  "policy": {
    "allowed_tools": ["search_docs"],
    "blocked_tools": [],
    "max_steps": 6,
    "max_tool_calls": 4,
    "max_tokens": 2000,
    "repeated_call_limit": 3,
    "allow_side_effects": false,
    "approval_required_tools": []
  },
  "faults": [
    {
      "type": "timeout",
      "tool_name": "search_docs",
      "call_index": 1,
      "probability": 1.0
    }
  ]
}
```

Fault decisions are deterministic for a given run seed and tool call index. `extra_latency` records deterministic delay metadata; it does not sleep or make local runs wall-clock dependent.

## Known Limitations

- The runtime is synchronous. It performs one model call or one tool call at a time.
- `FileEventStore` is local and single-process. It does not provide file locks, multi-writer coordination, retention, compaction, or remote storage.
- There is no distributed tracing or trace export. Event history is limited to the local JSONL and snapshot files.
- No real side-effect tools are implemented. `send_message` writes only to an in-memory `MessageRecorder`.
- `FakeAdapter` follows a scripted response list. Benchmark results describe fixture behavior, not model quality.
- `OpenAICompatibleAdapter` supports Chat Completions-compatible endpoints only. It is optional, and selecting it can contact the configured external endpoint.
- Runtime adapter exceptions are not converted into a persisted `RunFailed` event in `v0.1.0`. The replay engine can reconstruct `RunFailed` events, but the current runtime does not emit them.
- There is no HTTP API service, web UI, multi-agent orchestration, database, or distributed queue in this version.
- The package has not been validated as production infrastructure. Review dependencies, policies, storage, and deployment behavior before using it outside a local experiment.

## Development and Testing

Install the development dependencies and run the same gate used by CI:

```bash
python -m pip install -e ".[dev]"
ruff check .
mypy src
pytest --cov=agentlab --cov-fail-under=85
agentlab bench scenarios --runs-dir runs --fail-under 0.80
agentlab demo
```

GitHub Actions runs the suite on Python 3.11, 3.12, and 3.13. The local verification for this release produced 126 passing tests and 92.37% coverage. Coverage and benchmark values are evidence for this repository state and can change when the scenarios or tests change.

## Roadmap

`v0.1.0` intentionally keeps the surface small. Possible later work includes:

- A SQLite-backed run catalog for querying and retaining local runs.
- A read-only FastAPI service for run and report access.
- OpenTelemetry export for local and remote trace inspection.
- Parallel tool calls with explicit ordering and cancellation semantics.
- Scenario plugins for teams that want to keep their own fixture suites.
- Token and provider cost accounting for real model adapters.

These items are not part of the current release and should be designed and tested before they are added.
