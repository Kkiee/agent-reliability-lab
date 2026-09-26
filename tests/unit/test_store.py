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


def _assert_invalid_run_id_is_rejected_before_filesystem_access(
    store: FileEventStore,
    run_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = make_event(1, None).model_copy(update={"run_id": run_id})
    state = RuntimeState(run_id=run_id)
    operations = (
        lambda: store.start_run(run_id, {"scenario": "happy_path"}),
        lambda: store.append(event),
        lambda: store.read_events(run_id),
        lambda: store.write_state(state),
        lambda: store.load_state(run_id),
    )

    def unexpected_filesystem_access(*args: object, **kwargs: object) -> object:
        raise AssertionError("invalid run IDs must be rejected before filesystem access")

    for operation in operations:
        with monkeypatch.context() as patcher:
            patcher.setattr(Path, "exists", unexpected_filesystem_access)
            patcher.setattr(Path, "is_dir", unexpected_filesystem_access)
            patcher.setattr(Path, "mkdir", unexpected_filesystem_access)
            patcher.setattr(Path, "read_text", unexpected_filesystem_access)
            patcher.setattr(Path, "write_text", unexpected_filesystem_access)
            patcher.setattr(Path, "open", unexpected_filesystem_access)
            with pytest.raises(ValueError, match="run_id must be a single path segment"):
                operation()


@pytest.mark.parametrize("run_id", ["..", ".", "nested/run", "nested\\run"])
def test_store_rejects_dot_and_separator_run_ids_before_filesystem_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    run_id: str,
) -> None:
    store = FileEventStore(tmp_path)

    _assert_invalid_run_id_is_rejected_before_filesystem_access(store, run_id, monkeypatch)


def test_store_rejects_absolute_run_id_before_filesystem_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileEventStore(tmp_path)

    _assert_invalid_run_id_is_rejected_before_filesystem_access(
        store,
        str(tmp_path / "outside"),
        monkeypatch,
    )


def test_start_run_maps_mkdir_race_to_run_already_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileEventStore(tmp_path)
    original_mkdir = Path.mkdir

    def conflicting_mkdir(
        path: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        if path == tmp_path / "run-race":
            raise FileExistsError(path)
        original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", conflicting_mkdir)

    with pytest.raises(RunAlreadyExistsError):
        store.start_run("run-race", {"scenario": "happy_path"})
