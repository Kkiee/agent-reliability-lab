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

Day 3 adds:

- An append-only `FileEventStore` with canonical JSONL records, run manifests, terminal state snapshots, and SHA-256 event hash-chain verification.
- Canonical `RuntimeState` hashing and runtime persistence integration for saved run records.
- A deterministic `ReplayEngine` that reconstructs state only from persisted events and verifies the replay hash against the saved state hash without calling model adapters or tools.

Current limitations:

- `send_message` does not contact any external service; it only appends to an in-memory `MessageRecorder`.
- No real side-effect tools are implemented.
- File storage is local and single-process; it does not provide cross-process locking or distributed coordination.
- Chaos injection, scenario loading, reporting, and CLI support are not implemented yet.
