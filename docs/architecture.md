# Architecture

## Design Goals

The `v0.1.0` design keeps the execution path small enough to inspect and replay:

- Runtime state and event ordering are explicit.
- Model, policy, tool, chaos, and storage concerns have separate interfaces.
- The default execution path is deterministic and offline.
- Replay is read-only and does not repeat model calls or tool side effects.
- Event and state integrity failures are surfaced instead of being repaired silently.

This version is a local experiment harness. It is not designed as a distributed agent service.

## Runtime State Machine

`AgentRuntime` is synchronous. It starts a run, asks the model for one action, evaluates a tool request when needed, feeds the result back to the model, and stops on a final answer or a policy termination.

```text
RunStarted
    |
    v
RUNNING
    |
    +--> WAITING_FOR_MODEL --> ModelRequested --> ModelResponded
    |                                               |
    |                                               +--> FinalAnswer --> COMPLETED --> RunCompleted
    |                                               |
    |                                               +--> ToolCall
    |                                                        |
    |                                                        v
    |                                                  WAITING_FOR_TOOL
    |                                                        |
    |                                     PolicyEvaluated <-- ToolRequested
    |                                                        |
    |                       +--------------------------------+----------------------------+
    |                       |                                |                            |
    |                  terminate                           deny                         allow
    |                       |                                |                            |
    |                       v                                v                            v
    |                 RunTerminated                    ToolFailed or              ToolStarted
    |                 TERMINATED                      no result event                  |
    |                                                                             handler/fault
    |                                                                                   |
    |                                                                            ToolSucceeded
    |                                                                            or ToolFailed
    |                                                                                   |
    +-----------------------------------------------------------------------------------+
                                      next model step
```

`RunStatus.CREATED` is present on the domain model, but `AgentRuntime` immediately uses `RUNNING` after emitting `RunStarted`. `RunStatus.FAILED` and `EventType.RUN_FAILED` exist for replay compatibility; the current runtime does not convert model-adapter exceptions into a persisted `RunFailed` event. That behavior is a documented `v0.1.0` limitation, not a hidden success path.

A policy termination is terminal. A denied call is returned to the model as a failed tool result so the model can choose another action. A normal tool failure is also returned to the model; it does not automatically terminate the run.

## Event Model and Ordering

Every event contains:

- `event_id`: the run id and sequence number joined with `:`.
- `run_id`: the owning run.
- `seq`: a one-based sequence number.
- `type`: one of the `EventType` values.
- `timestamp`: supplied by the runtime clock. The default clock is deterministic.
- `payload`: event-specific data.
- `prev_hash`: the previous event's hash, or `null` for the first event.
- `hash`: the SHA-256 hash of the canonical event content.

The event hash is calculated from the canonical JSON representation of the event excluding its own `hash` field. The canonical form sorts keys, uses compact separators, and preserves non-ASCII text. `prev_hash` is part of the hashed content, so changing an earlier event breaks the chain at that event and at every later event.

The normal event order is:

1. `RunStarted`
2. For each model step: `ModelRequested`, then `ModelResponded`
3. For a final answer: `RunCompleted`
4. For a tool action: `ToolRequested`, then `PolicyEvaluated`
5. For a budget termination: `RunTerminated`
6. For an allowed tool: `ToolStarted`, then `ToolSucceeded` or `ToolFailed`
7. For a pre-execution timeout or tool error: `ToolStarted`, `FaultInjected`, `ToolFailed`
8. For `extra_latency`: `ToolStarted`, `FaultInjected`, `ToolSucceeded`
9. For a post-execution transformation: `ToolStarted`, `FaultInjected`, `ToolSucceeded`

A policy denial for an unknown tool emits `ToolFailed` because there is no registered handler. A policy denial for a registered tool records the decision in `PolicyEvaluated` and returns the denial to the model; the handler is not started. Replay reconstructs that denied result from the policy event.

## Event Log as the Source of Truth

`FileEventStore` writes canonical JSONL events under `runs/<run_id>/events.jsonl`. The runtime appends events in sequence and writes a terminal `state.json` snapshot after the run stops. The snapshot is useful for inspection, but it is not allowed to override the event history.

Replay starts with an empty `RuntimeState`, applies supported events in sequence, and computes a canonical state hash. It then reads the persisted state hash and rejects the run if the two hashes differ. Sequence gaps, non-canonical lines, broken previous hashes, invalid event payloads, and state snapshot mismatches raise `EventIntegrityError`.

This design makes the following possible:

- Reconstruct the final status, step count, token usage, tool history, and final answer.
- Explain which policy decision or fault affected a run.
- Detect accidental or deliberate edits to persisted events.
- Compare a replay result with the original run without trusting a mutable snapshot.

The repository does not claim that the filesystem is immutable or tamper-proof. The hash chain makes changes detectable; it is not an access-control mechanism.

## Why Replay Does Not Re-execute Tools

Replay applies `ToolSucceeded` and `ToolFailed` payloads directly to the reconstructed state. It never calls `ModelAdapter.complete`, `ToolRegistry.get`, or a tool handler. This is intentional:

- A tool may have an external side effect, so replay must not repeat it.
- A tool or model may be nondeterministic, so rerunning would create a different trajectory.
- The persisted event already contains the result that the original run observed.
- Keeping replay read-only makes incident review and regression checks safer.

Fault injection is also not rerun during replay. The original `FaultInjected` and tool-result events are already persisted, so replay uses those facts rather than re-evaluating probability.

## Policy Engine Check Order

`PolicyEngine.evaluate` checks conditions in a fixed order so the reason in `PolicyEvaluated` is stable and explainable:

1. `max_steps` is already reached or exceeded: terminate with `max_steps_exceeded`.
2. `max_tool_calls` is already reached or exceeded: terminate with `max_tool_calls_exceeded`.
3. `max_tokens` is already reached or exceeded: terminate with `token_budget_exceeded`.
4. The tool is not registered: deny with `unknown_tool`.
5. The tool is in `blocked_tools`: deny with `tool_blocked`.
6. The tool is not in `allowed_tools`: deny with `tool_not_allowed`.
7. The normalized call repeats enough history to reach `repeated_call_limit`: terminate with `repeated_tool_call`.
8. The registered tool has `side_effect=True` and `allow_side_effects=False`: deny with `side_effect_not_allowed`.
9. The tool is in `approval_required_tools`: deny with `approval_required`.
10. Otherwise: allow with `allowed`.

Repeated-call detection canonicalizes argument dictionaries before comparison, so argument key order does not affect the result. The runtime evaluates the policy before validating tool input or invoking a handler. Side effects therefore stay behind the policy boundary.

## Deterministic Chaos Injection

`ChaosInjector` uses only the run seed and the one-based tool call index for probability decisions:

```python
random.Random(seed + call_index).random() < probability
```

Fault specifications are also keyed by `(tool_name, call_index)`. Duplicate specifications for the same key are rejected when the injector is created. Earlier tool calls therefore cannot shift the random decision stream for later calls.

The pre-execution and post-execution behavior is deliberately distinct:

- `timeout` and `tool_error` emit a fault and a failed result without invoking the handler.
- `extra_latency` emits a fault, invokes the handler, and adds deterministic delay metadata. It does not call `sleep`.
- `malformed_json`, `empty_result`, `duplicate_result`, `prompt_injection`, and `contradictory_result` transform a successful handler result after execution and then emit the fault event before the tool result event.

The transformations use copied output and fixed payloads. They do not read the clock, global random state, environment variables, or network state.

## Current Concurrency and Persistence Limits

- The runtime is synchronous and single-threaded. It does not support parallel model calls or parallel tool calls.
- `FileEventStore` is a local filesystem store. Each append reads and validates the existing event file, then appends one canonical line. There is no cross-process lock, transaction, or writer coordination.
- Run directory creation uses `mkdir(exist_ok=False)`, which prevents two local processes from opening the same new run id at the same moment, but it does not make the event store safe for concurrent appenders.
- Events are not compressed, rotated, encrypted, replicated, or garbage-collected.
- There is no distributed trace context, remote event backend, or process-span correlation.
- Reports are derived from persisted facts, but report generation time is recorded separately and is not part of runtime state hashing.
- The current design favors simple local inspection over throughput, fault tolerance, or multi-tenant isolation.

These limits are part of the `v0.1.0` scope. Any change that adds concurrency, remote persistence, or real side-effect tools needs a separate design pass and corresponding tests.
