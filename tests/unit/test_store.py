import json
from pathlib import Path

import pytest

from agentlab.events import Event, compute_event_hash, compute_state_hash
from agentlab.models import EventType, RunStatus, RuntimeState
from agentlab.store import EventIntegrityError, FileEventStore, RunAlreadyExistsError


def make_event(seq: int, prev_hash: str | None) -> Event:
    return Event(
        event_id=f"event-{seq}",
        run_id="run-1",
        seq=seq,
        type=EventType.RUN_STARTED if seq == 1 else EventType.MODEL_REQUESTED,
        timestamp=f"2026-09-22T10:00:0{seq}Z",
        payload={"scenario": "happy_path", "seq": seq},
        prev_hash=prev_hash,
    )


def test_file_store_writes_hash_chain(tmp_path: Path) -> None:
    store = FileEventStore(tmp_path)
    store.start_run("run-1", {"scenario": "happy_path", "seed": 42})
    first = store.append(make_event(1, None))
    second = store.append(make_event(2, first.hash))

    events = store.read_events("run-1")
    assert [event.hash for event in events] == [first.hash, second.hash]
    assert second.prev_hash == first.hash


def test_tampered_event_log_is_rejected(tmp_path: Path) -> None:
    store = FileEventStore(tmp_path)
    store.start_run("run-1", {"scenario": "happy_path", "seed": 42})
    store.append(make_event(1, None))
    path = tmp_path / "run-1" / "events.jsonl"
    path.write_text(
        path.read_text(encoding="utf-8").replace("happy_path", "bad_path"),
        encoding="utf-8",
    )

    with pytest.raises(EventIntegrityError):
        store.read_events("run-1")


def test_existing_run_cannot_be_overwritten(tmp_path: Path) -> None:
    store = FileEventStore(tmp_path)
    store.start_run("run-1", {"scenario": "happy_path"})
    original = store.append(make_event(1, None))
    path = tmp_path / "run-1" / "events.jsonl"

    with pytest.raises(RunAlreadyExistsError):
        store.start_run("run-1", {"scenario": "changed"})

    assert path.read_text(encoding="utf-8").strip() == json.dumps(
        original.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def test_store_rejects_sequence_gap(tmp_path: Path) -> None:
    store = FileEventStore(tmp_path)
    store.start_run("run-1", {"scenario": "happy_path"})
    store.append(make_event(1, None))

    with pytest.raises(EventIntegrityError):
        store.append(make_event(3, store.read_events("run-1")[-1].hash))


def test_store_rejects_mismatched_prev_hash(tmp_path: Path) -> None:
    store = FileEventStore(tmp_path)
    store.start_run("run-1", {"scenario": "happy_path"})
    store.append(make_event(1, None))

    with pytest.raises(EventIntegrityError):
        store.append(make_event(2, "wrong-prev-hash"))


def test_store_rejects_explicit_mismatched_hash(tmp_path: Path) -> None:
    store = FileEventStore(tmp_path)
    store.start_run("run-1", {"scenario": "happy_path"})
    event = make_event(1, None).model_copy(update={"hash": "0" * 64})

    with pytest.raises(EventIntegrityError):
        store.append(event)


def test_event_log_uses_canonical_json_per_line(tmp_path: Path) -> None:
    store = FileEventStore(tmp_path)
    store.start_run("run-1", {"scenario": "happy_path", "seed": 42})
    first = store.append(make_event(1, None))
    second = store.append(make_event(2, first.hash))

    lines = (tmp_path / "run-1" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line) for line in lines] == [
        first.model_dump(mode="json"),
        second.model_dump(mode="json"),
    ]
    assert lines == [
        json.dumps(
            event.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for event in (first, second)
    ]


def test_state_snapshot_round_trips_with_hash(tmp_path: Path) -> None:
    store = FileEventStore(tmp_path)
    store.start_run("run-1", {"scenario": "happy_path", "seed": 42})
    state = RuntimeState(
        run_id="run-1",
        status=RunStatus.COMPLETED,
        step=2,
        token_usage=9,
        final_answer="done",
    )

    store.write_state(state)

    assert store.load_state("run-1") == state
    assert store.load_state_hash("run-1") == compute_state_hash(state)


def test_store_rejects_event_from_another_run(tmp_path: Path) -> None:
    store = FileEventStore(tmp_path)
    store.start_run("run-1", {"scenario": "happy_path"})
    event = make_event(1, None).model_copy(update={"run_id": "run-2"})
    event = event.model_copy(update={"hash": compute_event_hash(event)})
    path = tmp_path / "run-1" / "events.jsonl"
    path.write_text(
        json.dumps(
            event.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    with pytest.raises(EventIntegrityError):
        store.read_events("run-1")
