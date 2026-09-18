from datetime import datetime, timedelta, timezone
import pytest
from earthglass.spatial.models import Observation, Viewport
from earthglass.spatial.history import SpatialHistory


def observation(ident="test:1", lon=10.0, at=None):
    return Observation(
        entity_id=ident,
        entity_type="aircraft",
        layer="aircraft",
        position={"latitude": 1.0, "longitude": lon},
        observed_at=at or datetime.now(timezone.utc),
        provenance={
            "provider": "test",
            "source_id": ident,
            "source_url": "https://example.com/",
            "attribution": "Test",
        },
    )


def test_identity_deduplication_and_out_of_order_history(tmp_path):
    store = SpatialHistory(tmp_path / "history.db")
    newer = observation()
    older = observation(at=newer.observed_at - timedelta(minutes=1), lon=20.0)
    try:
        assert len(store.ingest([newer])) == 1
        assert store.ingest([newer]) == []
        assert store.ingest([older]) == []
        assert store.query()["observations"][0]["position"]["longitude"] == 10
        assert (
            store.query(at=older.observed_at)["observations"][0]["position"][
                "longitude"
            ]
            == 20
        )
        assert len(store.query(entity_id="test:1")["observations"]) == 2
    finally:
        store.close()


def test_dateline_viewport_and_pagination(tmp_path):
    store = SpatialHistory(tmp_path / "history.db")
    try:
        store.ingest(
            [observation("a", 179.0), observation("b", -179.0), observation("c", 0.0)]
        )
        result = store.query(
            viewport=Viewport(west=170, south=-10, east=-170, north=10), limit=1
        )
        assert len(result["observations"]) == 1
        assert result["next_cursor"] == 1
        assert store.query(
            viewport=Viewport(west=170, south=-10, east=-170, north=10), cursor=1
        )["observations"][0]["entity_id"] in {"a", "b"}
    finally:
        store.close()


def test_retention_removes_expired_entities_and_emits_tombstone(tmp_path):
    store = SpatialHistory(tmp_path / "history.db", retention_days=7)
    try:
        item = observation()
        store.ingest([item])
        store.prune(now=item.received_at.timestamp() + 8 * 86400)
        assert store.query()["observations"] == []
        assert store.changes(1)["changes"][-1]["operation"] == "remove"
    finally:
        store.close()


@pytest.mark.parametrize(
    "position",
    [
        {"latitude": True, "longitude": 0.0},
        {"latitude": 91.0, "longitude": 0.0},
        {"latitude": 0.0, "longitude": float("nan")},
        {"latitude": 0.0, "longitude": 0.0, "altitude_m": float("inf")},
    ],
)
def test_invalid_coordinates_rejected(position):
    wire = observation().wire()
    wire["position"] = position
    with pytest.raises(ValueError):
        Observation.model_validate(wire)


def test_naive_timestamp_and_unexplained_confidence_rejected():
    wire = observation().wire()
    wire["observed_at"] = "2026-01-01T00:00:00"
    with pytest.raises(ValueError):
        Observation.model_validate(wire)
    wire = observation().wire()
    wire["confidence"] = {"value": 0.9}
    with pytest.raises(ValueError):
        Observation.model_validate(wire)


def test_pagination_is_frozen_while_contacts_move(tmp_path):
    store = SpatialHistory(tmp_path / "pages.db")
    try:
        now = datetime.now(timezone.utc)
        store.ingest(
            [observation(str(i), at=now - timedelta(seconds=i)) for i in range(4)]
        )
        first = store.query(limit=2)
        store.ingest(
            [
                observation("3", lon=30, at=now + timedelta(seconds=1)),
                observation("new", at=now + timedelta(seconds=2)),
            ]
        )
        second = store.query(limit=2, cursor=2, snapshot_rowid=first["snapshot_rowid"])
        assert [
            o["entity_id"] for o in first["observations"] + second["observations"]
        ] == ["0", "1", "2", "3"]
        assert second["observations"][-1]["position"]["longitude"] == 10
        assert len(store.changes(first["sequence"])["changes"]) == 2
    finally:
        store.close()


def test_coalesced_delivery_preserves_fairness(tmp_path):
    store = SpatialHistory(tmp_path / "fair.db")
    try:
        now = datetime.now(timezone.utc)
        store.ingest([observation("a", at=now), observation("b", at=now)])
        store.acknowledge_publications(store.pending_publications(1))
        store.ingest(
            [
                observation("a", at=now + timedelta(seconds=1)),
                observation("b", at=now + timedelta(seconds=1)),
            ]
        )
        assert store.pending_publications(1)[0]["observation"]["entity_id"] == "b"
    finally:
        store.close()


def test_provenance_rejects_executable_links():
    wire = observation().wire()
    wire["provenance"]["source_url"] = "javascript:alert(1)"
    with pytest.raises(ValueError):
        Observation.model_validate(wire)
