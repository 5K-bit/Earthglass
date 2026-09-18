from datetime import datetime, timedelta, timezone
import csv, io, zipfile
import pytest
from google.transit import gtfs_realtime_pb2 as gtfs
from earthglass.mobility.transit import GTFSRealtimeFeed
from earthglass.mobility.traffic import NY511Feed, NYCDOTFeed
from earthglass.mobility.static_gtfs import import_gtfs, StaticGTFSFeed
from earthglass.spatial.models import Viewport
from earthglass.spatial.network import ProviderError

NOW = datetime.now(timezone.utc)
AREA = Viewport(west=-75, south=39, east=-73, north=42)


class HTTP:
    offline = False

    def __init__(self, data):
        self.data = data

    def bytes(self, *a, **kw):
        return self.data, "application/x-protobuf"

    def json(self, *a, **kw):
        return self.data

    def text(self, *a, **kw):
        return self.data


def message():
    feed = gtfs.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = int(NOW.timestamp())
    return feed


def test_gtfs_actual_coordinates_null_motion_and_nonspatial_reports(tmp_path):
    feed = message()
    v = feed.entity.add()
    v.id = "bus"
    v.vehicle.vehicle.id = "10"
    v.vehicle.position.latitude = 40.5
    v.vehicle.position.longitude = -74
    v.vehicle.trip.route_id = "M1"
    no = feed.entity.add()
    no.id = "train"
    no.vehicle.stop_id = "station"
    no.vehicle.vehicle.id = "11"
    a = feed.entity.add()
    a.id = "alert"
    a.alert.header_text.translation.add(text="Fixture delay", language="en")
    a.alert.informed_entity.add(route_id="M1")
    adapter = GTFSRealtimeFeed(HTTP(feed.SerializeToString()))
    adapter.configure_cache(tmp_path)
    values = adapter.fetch(AREA, NOW)
    assert len(values) == 1 and values[0].motion.speed_mps is None
    assert values[0].properties["route_id"] == "M1"
    doc = adapter.document()["data"]
    assert (
        doc["unlocated_vehicles"] == 1 and doc["alerts"][0]["header"] == "Fixture delay"
    )


def test_gtfs_differential_and_future_feed_rejected(tmp_path):
    feed = message()
    feed.header.incrementality = gtfs.FeedHeader.DIFFERENTIAL
    adapter = GTFSRealtimeFeed(HTTP(feed.SerializeToString()))
    adapter.configure_cache(tmp_path)
    with pytest.raises(ProviderError) as exc:
        adapter.fetch(AREA, NOW)
    assert exc.value.code == "differential_unsupported"
    feed.header.incrementality = gtfs.FeedHeader.FULL_DATASET
    feed.header.timestamp = int((NOW + timedelta(days=1)).timestamp())
    adapter.http.data = feed.SerializeToString()
    with pytest.raises(ProviderError):
        adapter.fetch(AREA, NOW)


def test_511_free_key_optional_but_required_when_enabled():
    adapter = NY511Feed(HTTP([]))
    with pytest.raises(ProviderError) as exc:
        adapter.fetch(AREA, NOW)
    assert exc.value.code == "credential_required"


def test_511_incidents_coordinates_and_source_time():
    row = {
        "ID": "fixture",
        "Latitude": 40.5,
        "Longitude": -74,
        "EventType": "closures",
        "RoadwayName": "Fixture road",
        "Description": "Fixture closure",
        "LastUpdated": int(NOW.timestamp()),
        "IsFullClosure": True,
    }
    value = NY511Feed(HTTP([row]), lambda _: "fixture-key").fetch(AREA, NOW)[0]
    assert value.properties[
        "full_closure"
    ] and value.observed_at == datetime.fromtimestamp(
        int(NOW.timestamp()), timezone.utc
    )


def test_511_camera_catalog_rejects_http_embedded_feeds():
    row = {
        "Id": 1,
        "Latitude": 40.5,
        "Longitude": -74,
        "Views": [{"Id": 1, "Url": "http://localhost:54134/map/Cctv/1"}],
    }
    value = NY511Feed(HTTP([row]), lambda _: "fixture-key", product="cameras").fetch(
        AREA, NOW
    )[0]
    assert value.properties["views"][0]["url"] is None
    assert value.measurement_kind == "catalog"


def archive():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("routes.txt", "route_id,route_short_name,route_type\nR,R1,3\n")
        z.writestr("trips.txt", "route_id,trip_id,shape_id\nR,T,S\n")
        z.writestr(
            "shapes.txt",
            "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\nS,40,-74,1\nS,41,-74,2\n",
        )
        z.writestr(
            "stops.txt",
            "stop_id,stop_name,stop_lat,stop_lon\nA,Fixture stop,40.5,-74\n",
        )
        z.writestr("../never-extract.txt", "No extraction")
    return buffer.getvalue()


def test_static_gtfs_import_and_offline_restart(tmp_path):
    document = import_gtfs(
        archive(),
        agency="fixture",
        source_url="https://example.org/gtfs",
        attribution="Fixture agency",
    )
    assert document["route_count"] == 1 and document["stop_count"] == 1
    adapter = StaticGTFSFeed(HTTP(None))
    adapter.configure_cache(tmp_path)
    adapter.install(document)
    restored = StaticGTFSFeed(HTTP(None))
    restored.http.offline = True
    restored.configure_cache(tmp_path)
    values = restored.fetch(AREA, NOW)
    assert (
        len(values) == 1
        and values[0].measurement_kind == "catalog"
        and values[0].properties["route_id"] == "R"
    )
    assert not (tmp_path.parent / "never-extract.txt").exists()
    stops = StaticGTFSFeed(HTTP(None), stops=True)
    stops.configure_cache(tmp_path)
    assert stops.fetch(AREA, NOW)[0].properties["stop_id"] == "A"
    with pytest.raises(ValueError):
        import_gtfs(
            archive(),
            agency="../escape",
            source_url="https://example.org",
            attribution="Fixture",
        )
    with pytest.raises(ValueError):
        import_gtfs(
            archive(),
            agency="fixture",
            source_url="javascript:alert(1)",
            attribution="Fixture",
        )


def test_nyc_sensor_time_and_zero_are_not_invented_congestion():
    from zoneinfo import ZoneInfo

    output = io.StringIO()
    fields = [
        "id",
        "Speed",
        "TravelTime",
        "Status",
        "DataAsOf",
        "linkId",
        "EncodedPolyLine",
        "linkName",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, delimiter="\t")
    writer.writeheader()
    encoded = "_p~iF~ps|U_ulLnnqC_mqNvxq" + chr(96) + "@"
    writer.writerow(
        dict(
            zip(
                fields,
                [
                    "1",
                    "0",
                    "0",
                    "-101",
                    NOW.astimezone(ZoneInfo("America/New_York")).strftime(
                        "%m/%d/%Y %H:%M:%S"
                    ),
                    "road",
                    encoded,
                    "Fixture road",
                ],
            )
        )
    )
    adapter = NYCDOTFeed(HTTP(output.getvalue()))
    region = Viewport(west=-127, south=36, east=-119, north=44)
    value = adapter.fetch(region, NOW)[0]
    assert (
        value.properties["speed_mps"] is None
        and value.properties["congestion"] == "unknown"
    )
    assert not value.properties["sensor_available"]


def test_winter_roads_polyline_only_parts_and_credential_urls():
    from earthglass.mobility.traffic import public_link

    encoded = "_p~iF~ps|U_ulLnnqC_mqNvxq" + chr(96) + "@"
    row = {
        "Id": "road",
        "EncodedPolyline": [encoded, encoded],
        "Condition": ["Snow"],
        "RoadwayName": "Fixture",
        "LastUpdated": int(NOW.timestamp()),
    }
    values = NY511Feed(
        HTTP([row]), lambda _: "fixture-key", product="conditions"
    ).fetch(Viewport(west=-127, south=36, east=-119, north=44), NOW)
    assert len(values) == 2 and len({v.entity_id for v in values}) == 2
    assert all(v.properties["type"] == "weather_condition" for v in values)
    assert values[0].properties["geometry"]["type"] == "LineString"
    for url in (
        "https://localhost/camera",
        "https://127.0.0.1/camera",
        "https://example.org/?api_key=private",
        "https://example.org/?token=private",
    ):
        assert public_link(url) is None
    assert public_link("https://511ny.org/camera/1") == "https://511ny.org/camera/1"
