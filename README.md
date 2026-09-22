# Agent Reliability Lab

Reliability tests, deterministic replay, and fault injection for tool-using agents.

## Install

```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
python -m pip install -e ".[dev]"
```

## Status

Day 1: deterministic runtime core and `FakeAdapter` are implemented. Tool execution,
fault injection, replay, scenarios, and reporting arrive in later tasks.