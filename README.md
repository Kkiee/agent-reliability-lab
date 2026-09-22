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

Day 1: deterministic runtime core and `FakeAdapter` are implemented. Tool execution,
fault injection, replay, scenarios, and reporting arrive in later tasks.
