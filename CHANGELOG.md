# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-09

### Added

- A synchronous, framework-independent `AgentRuntime` with structured model and tool actions.
- Pydantic 2 domain models for scenarios, policies, faults, tool calls, tool results, events, and run records.
- A deterministic `FakeAdapter` and an optional OpenAI Chat Completions-compatible adapter.
- An append-only JSONL event store with canonical records, SHA-256 event hash chains, run manifests, and state snapshots.
- A replay engine that reconstructs runtime state from persisted events without invoking model adapters or tool handlers.
- A pre-execution policy engine with step, tool-call, token, allow/block list, repeated-call, side-effect, and approval checks.
- Validated mock tools for document search, record lookup, restricted arithmetic, and in-memory message recording.
- Deterministic fault injection for timeout, tool error, malformed JSON, empty result, duplicate result, extra latency metadata, prompt injection, and contradictory evidence.
- Nine fixture scenarios covering successful execution, recovery paths, loop and budget termination, policy denial, prompt injection, and contradictory evidence.
- JSON and offline HTML reports for benchmark summaries and individual runs.
- A Typer CLI with `list-scenarios`, `run`, `replay`, `report`, `bench`, and `demo` commands.
- README, architecture documentation, examples, MIT License, and GitHub Actions configuration.

### Changed

- `v0.1.0` is the first public release, so no upgrade or migration path is required.
- Policy decisions are applied before tool execution, and replay reconstructs tool results from persisted policy and result events rather than rerunning tools.
- Default benchmark, demo, and CLI execution use `FakeAdapter`; the OpenAI-compatible adapter is opt-in.

### Security

- Event records are canonicalized and linked with SHA-256 hashes, and replay verifies the chain before reconstructing state.
- State snapshots are checked against the canonical runtime state hash.
- Side-effecting tools are denied by default; the repository contains only mock tools, and `send_message` writes to memory only.
- Model credentials are read from environment variables at runtime and are not stored in scenario files or run records.

### Known Limitations

- Execution is synchronous and processes one model or tool call at a time.
- Event storage is local and single-process with no cross-process locking, distributed coordination, retention policy, or compaction.
- There is no distributed tracing, OpenTelemetry export, HTTP API, web UI, database, or distributed queue in `v0.1.0`.
- `FakeAdapter` is a deterministic fixture adapter, so benchmark metrics do not measure real model quality or rank models.
- No real side-effect tools are included; `send_message` only records messages in memory.
- `extra_latency` records deterministic delay metadata but does not sleep.
- Runtime adapter exceptions are not converted into a persisted `RunFailed` event in this version, although replay can reconstruct `RunFailed` records.
- The OpenAI-compatible adapter supports Chat Completions-compatible endpoints only.
- The project has not been validated as production infrastructure. See the README for the current operational and storage boundaries.

[Unreleased]: https://github.com/Kkiee/agent-reliability-lab/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Kkiee/agent-reliability-lab/releases/tag/v0.1.0
