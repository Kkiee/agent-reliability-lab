# Agent Reliability Lab

Reliability tests, deterministic replay, and fault injection for tool-using agents.

## Install

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

### POSIX (bash/zsh)

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Status

Day 1 provides a deterministic runtime core and `FakeAdapter`.

Day 2 adds:

- Pydantic policy configuration and a pre-execution policy engine with budgets, allow/block lists, repeated-call termination, and side-effect denial by default.
- A tool registry with validated Pydantic input schemas and the mock tools `search_docs`, `fetch_record`, `calculate`, and `send_message`.
- A synchronous runtime tool loop that records `ToolRequested`, `PolicyEvaluated`, `ToolStarted`, `ToolSucceeded`, and `ToolFailed` events.

Current limitations:

- `send_message` does not contact any external service; it only appends to an in-memory `MessageRecorder`.
- No real side-effect tools are implemented.
- Replay, chaos injection, scenarios, reporting, and CLI support are not implemented yet.
