from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from agentlab.events import Event, compute_event_hash, compute_state_hash
from agentlab.models import RuntimeState, StrictModel


class EventIntegrityError(ValueError):
    pass


class RunAlreadyExistsError(FileExistsError):
    pass


class _RunManifest(StrictModel):
    schema_version: int = 1
    run_id: str
    metadata: dict[str, object]


class _StateSnapshot(StrictModel):
    run_id: str
    state: RuntimeState
    state_hash: str


def _canonical_json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class FileEventStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def start_run(self, run_id: str, metadata: dict[str, object]) -> None:
        run_dir = self._run_dir(run_id)
        try:
            run_dir.mkdir(exist_ok=False)
        except FileExistsError as exc:
            raise RunAlreadyExistsError(run_id) from exc
        manifest = _RunManifest(run_id=run_id, metadata=metadata)
        _write_json(run_dir / "manifest.json", manifest.model_dump(mode="json"))
        (run_dir / "events.jsonl").write_text("", encoding="utf-8")

    def append(self, event: Event) -> Event:
        events_path = self._events_path(event.run_id)
        events = self.read_events(event.run_id)
        expected_seq = len(events) + 1
        expected_prev_hash = events[-1].hash if events else None

        if event.seq != expected_seq:
            raise EventIntegrityError(
                f"sequence gap: expected {expected_seq}, received {event.seq}"
            )
        if event.prev_hash != expected_prev_hash:
            raise EventIntegrityError("previous event hash does not match the hash chain")

        computed_hash = compute_event_hash(event)
        if event.hash and event.hash != computed_hash:
            raise EventIntegrityError("event hash does not match its canonical content")

        stored = event.model_copy(update={"hash": computed_hash})
        with events_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical_json(stored.model_dump(mode="json")))
            handle.write("\n")
        return stored

    def read_events(self, run_id: str) -> list[Event]:
        path = self._events_path(run_id)
        if not path.is_file():
            raise EventIntegrityError(f"run does not exist: {run_id}")

        events: list[Event] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            try:
                event = Event.model_validate(json.loads(line))
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                raise EventIntegrityError(f"invalid event at line {line_number}") from exc

            if event.run_id != run_id:
                raise EventIntegrityError(f"run id mismatch at line {line_number}")

            canonical = _canonical_json(event.model_dump(mode="json"))
            if line != canonical:
                raise EventIntegrityError(f"event at line {line_number} is not canonical")

            expected_seq = len(events) + 1
            expected_prev_hash = events[-1].hash if events else None
            if event.seq != expected_seq:
                raise EventIntegrityError(f"sequence gap at line {line_number}")
            if event.prev_hash != expected_prev_hash:
                raise EventIntegrityError(f"hash chain mismatch at line {line_number}")
            if not event.hash or event.hash != compute_event_hash(event):
                raise EventIntegrityError(f"event hash mismatch at line {line_number}")
            events.append(event)

        return events

    def write_state(self, state: RuntimeState) -> None:
        run_dir = self._run_dir(state.run_id)
        if not run_dir.is_dir():
            raise EventIntegrityError(f"run does not exist: {state.run_id}")
        snapshot = _StateSnapshot(
            run_id=state.run_id,
            state=state,
            state_hash=compute_state_hash(state),
        )
        _write_json(run_dir / "state.json", snapshot.model_dump(mode="json"))

    def load_state(self, run_id: str) -> RuntimeState:
        return self._load_snapshot(run_id).state

    def load_state_hash(self, run_id: str) -> str:
        snapshot = self._load_snapshot(run_id)
        if snapshot.state_hash != compute_state_hash(snapshot.state):
            raise EventIntegrityError("state snapshot hash mismatch")
        return snapshot.state_hash

    def _load_snapshot(self, run_id: str) -> _StateSnapshot:
        path = self._run_dir(run_id) / "state.json"
        try:
            snapshot = _StateSnapshot.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise EventIntegrityError(f"invalid state snapshot for run: {run_id}") from exc
        if snapshot.run_id != run_id or snapshot.state.run_id != run_id:
            raise EventIntegrityError("state snapshot run id mismatch")
        return snapshot

    def _run_dir(self, run_id: str) -> Path:
        if (
            not run_id
            or run_id in {".", ".."}
            or "/" in run_id
            or "\\" in run_id
            or Path(run_id).is_absolute()
            or Path(run_id).name != run_id
        ):
            raise ValueError("run_id must be a single path segment and cannot be '.' or '..'")
        return self.root / run_id

    def _events_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "events.jsonl"


def _write_json(path: Path, data: object) -> None:
    path.write_text(_canonical_json(data), encoding="utf-8")
