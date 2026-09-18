from datetime import datetime, timezone
from dataclasses import replace
import pytest
from earthglass.spatial.models import Viewport
from earthglass.spatial.feeds.aviation import AircraftFeed, MilitaryFeed
from earthglass.spatial.feeds.maritime import VesselFeed
from earthglass.spatial.feeds.environment import (
    EarthquakeFeed,
    FiresFeed,
    WeatherFeed,
    TemperatureFeed,
)
from earthglass.spatial.feeds.space import SatelliteFeed, LaunchFeed, teme_to_wgs84
from earthglass.spatial.feeds.local_context import (
    InfrastructureFeed,
    TrafficFeed,
    BikeshareFeed,
    TfLCameraFeed,
    CaltransCameraFeed,
)
from earthglass.spatial.network import ProviderError, public_address, PublicHTTP

NOW = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
VIEW = Viewport(west=-75, south=39, east=-73, north=41)
GLOBE = Viewport(west=-180, south=-90, east=180, north=90)


class HTTP:
    def __init__(self, data=None, text=""):
        self.data = data
        self.body = text
        self.calls = []

    def json(self, url, **kwargs):
        self.calls.append(url)
        return self.data(url) if callable(self.data) else self.data

    def text(self, url, **kwargs):
        return self.body


@pytest.mark.parametrize("cls", [AircraftFeed, MilitaryFeed])
def test_aircraft_units_and_missing_motion(cls):
    feed = cls(HTTP())
    values = feed.from_adsb(
        {
            "now": NOW.timestamp(),
            "ac": [
                {
                    "hex": "ABC",
                    "lat": 40,
                    "lon": -74,
                    "alt_baro": 10000,
                    "gs": 100,
                    "seen_pos": 2,
                }
            ],
        },
        NOW,
        VIEW,
    )
    assert values[0].position.altitude_m == 3048
    assert values[0].motion.speed_mps == pytest.approx(51.4444)
    assert values[0].motion.heading_deg is None
    assert values[0].position.altitude_reference == "barometric"
    assert values[0].observed_at.second == 58
    assert values[0].layer == cls.spec.layer


def test_malformed_aircraft_is_rejected_not_zeroed():
    feed = AircraftFeed(HTTP())
    with pytest.raises(ProviderError):
        feed.from_adsb(
            {"now": NOW.timestamp(), "ac": [{"hex": "bad", "lat": 400, "lon": 0}]},
            NOW,
            GLOBE,
        )


def test_vessel_unknown_heading_speed_are_null():
    feed = VesselFeed(HTTP())
    value = feed.parse_message(
        {
            "MessageType": "PositionReport",
            "MetaData": {"MMSI": 123, "time_utc": "2026-09-10 12:00:00.000 +0000 UTC"},
            "Message": {
                "PositionReport": {
                    "Latitude": 40,
                    "Longitude": -74,
                    "TrueHeading": 511,
                    "Cog": 360,
                    "Sog": 102.3,
                }
            },
        },
        NOW,
    )
    assert value.motion.heading_deg is None and value.motion.speed_mps is None


def test_earthquake_depth_is_separate():
    values = EarthquakeFeed(
        HTTP(
            {
                "features": [
                    {
                        "id": "quake",
                        "geometry": {"coordinates": [-74, 40, 12]},
                        "properties": {"time": NOW.timestamp() * 1000, "mag": 2},
                    }
                ]
            }
        )
    ).fetch(VIEW, NOW)
    assert values[0].position.altitude_m is None
    assert values[0].properties["depth_m"] == 12000


def test_fires_timestamp_and_credential():
    csv = "latitude,longitude,acq_date,acq_time,confidence,bright_ti4,frp\n40,-74,2026-09-10,123,n,301,2\n"
    feed = FiresFeed(HTTP(text=csv), lambda _: "fixture-key")
    value = feed.fetch(VIEW, NOW)[0]
    assert value.observed_at.hour == 1 and value.observed_at.minute == 23
    assert "fixture-key" not in str(value.wire())
    with pytest.raises(ProviderError, match="Configure"):
        FiresFeed(HTTP()).fetch(VIEW, NOW)


@pytest.mark.parametrize("cls", [WeatherFeed, TemperatureFeed])
def test_weather_is_model_prediction(cls):
    data = {
        "latitude": 40,
        "longitude": -74,
        "current": {"time": "2026-09-10T12:00", "temperature_2m": 21},
    }
    value = cls(HTTP(data)).fetch(VIEW, NOW)[0]
    assert (
        value.measurement_kind == "predicted"
        and value.properties["temperature_c"] == 21
    )


def test_satellite_is_propagated_prediction():
    tle = "ISS\n1 25544U 98067A   24287.54791435  .00016717  00000+0  30189-3 0  9997\n2 25544  51.6416  25.9570 0003749  62.4283  58.7756 15.49824920475637\n"
    now = datetime(2024, 10, 13, 12, tzinfo=timezone.utc)
    values = SatelliteFeed(HTTP(text=tle)).fetch(GLOBE, now)
    assert values and values[0].measurement_kind == "predicted"
    assert -90 <= values[0].position.latitude <= 90
    assert values[0].position.altitude_m > 100000


def test_launch_is_catalog_not_live_ascent():
    data = {
        "results": [
            {
                "id": "one",
                "name": "Launch",
                "net": "2026-09-11T00:00:00Z",
                "pad": {"latitude": 40, "longitude": -74},
            }
        ]
    }
    value = LaunchFeed(HTTP(data)).fetch(VIEW, NOW)[0]
    assert value.measurement_kind == "catalog" and value.properties["scheduled_at"]


def osm():
    return {
        "elements": [
            {
                "type": "node",
                "id": 1,
                "lat": 40,
                "lon": -74,
                "tags": {"name": "Infrastructure"},
            }
        ]
    }


def test_infrastructure_and_road_catalogs():
    value = InfrastructureFeed(HTTP(osm())).fetch(VIEW, NOW)[0]
    assert value.measurement_kind == "catalog"
    road = TrafficFeed(HTTP(osm())).fetch(VIEW, NOW)[0]
    assert road.properties["traffic_state"] == "catalog"


def test_road_catalog_never_uses_credentials_or_claims_live_flow():
    data = {"elements": [{"type": "way", "id": 42, "center": {"lat": 40, "lon": -74}, "tags": {"name": "Road"}}]}
    def credential(_):
        raise AssertionError("Road catalog must not read credentials")
    http = HTTP(data)
    value = TrafficFeed(http, credential).fetch(VIEW, NOW)[0]
    assert value.measurement_kind == "catalog"
    assert value.properties["traffic_state"] == "catalog"
    assert "retention_seconds" not in value.properties
    assert "current_speed_mps" not in value.properties
    assert value.provenance.provider == "overpass_roads"


def test_bikeshare_joins_catalog_and_status():
    def data(url):
        if "gbfs.json" in url:
            return {
                "data": {
                    "en": {
                        "feeds": [
                            {
                                "name": "station_information",
                                "url": "https://example.org/info",
                            },
                            {
                                "name": "station_status",
                                "url": "https://example.org/status",
                            },
                        ]
                    }
                }
            }
        if url.endswith("info"):
            return {
                "data": {
                    "stations": [
                        {"station_id": "1", "lat": 40, "lon": -74, "name": "Station"}
                    ]
                }
            }
        return {
            "last_updated": NOW.timestamp(),
            "data": {
                "stations": [
                    {
                        "station_id": "1",
                        "num_bikes_available": 4,
                        "last_reported": NOW.timestamp(),
                    }
                ]
            },
        }

    value = BikeshareFeed(HTTP(data)).fetch(VIEW, NOW)[0]
    assert value.properties["bikes_available"] == 4


def test_public_camera_metadata_never_claims_calibrated_pose():
    tfl = [
        {
            "id": "cam",
            "lat": 40,
            "lon": -74,
            "commonName": "Camera",
            "additionalProperties": [
                {"key": "imageUrl", "value": "https://example.org/frame.jpg"}
            ],
        }
    ]
    assert (
        TfLCameraFeed(HTTP(tfl)).fetch(VIEW, NOW)[0].properties["pose"]
        == "uncalibrated"
    )
    caltrans = {
        "data": [
            {
                "cctv": {
                    "index": 1,
                    "location": {
                        "locationName": "Road",
                        "latitude": 40,
                        "longitude": -74,
                    },
                    "imageData": {
                        "static": {"currentImageURL": "https://example.org/frame.jpg"}
                    },
                }
            }
        ]
    }
    assert (
        CaltransCameraFeed(HTTP(caltrans)).fetch(VIEW, NOW)[0].entity_type == "camera"
    )


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1"]
)
def test_provider_transport_rejects_private_dns(address):
    with pytest.raises(ProviderError):
        public_address(
            "example.org", lambda *a, **k: [(None, None, None, None, (address, 443))]
        )


def test_transport_bounds_responses_and_rejects_redirects():
    import httpx

    resolver = lambda *a, **k: [(None, None, None, None, ("8.8.8.8", 443))]
    for response, code in [
        (
            httpx.Response(302, headers={"Location": "http://127.0.0.1"}),
            "redirect_rejected",
        ),
        (httpx.Response(429), "rate_limited"),
        (httpx.Response(200, content=b"x" * 101), "response_too_large"),
    ]:
        http = PublicHTTP(
            max_bytes=100,
            resolver=resolver,
            transport_factory=lambda: httpx.MockTransport(lambda req: response),
        )
        with pytest.raises(ProviderError) as exc:
            http.bytes("https://example.org/data")
        assert exc.value.code == code
        http.close()


def test_perception_is_camera_location_and_requires_configuration():
    from earthglass.spatial.feeds.perception import PerceptionFeed

    feed = PerceptionFeed(HTTP())
    with pytest.raises(ProviderError):
        feed.fetch(VIEW, NOW)
    feed.configure(
        lambda limit: [
            {
                "event_id": "motion1",
                "timestamp": NOW.isoformat(),
                "payload": {"camera_id": "0", "confidence": 0.8},
            }
        ],
        {"0": {"latitude": 40, "longitude": -74}},
    )
    value = feed.fetch(VIEW, NOW)[0]
    assert value.measurement_kind == "estimated"
    assert value.properties["location_basis"].endswith("object position is unknown")
    assert value.confidence is None


def test_military_and_civil_records_keep_separate_layer_identity():
    data = {"now": NOW.timestamp(), "ac": [{"hex": "ABC", "lat": 40, "lon": -74}]}
    civil = AircraftFeed(HTTP()).from_adsb(data, NOW, VIEW)[0]
    military = MilitaryFeed(HTTP()).from_adsb(data, NOW, VIEW)[0]
    assert civil.entity_id != military.entity_id
    assert (
        civil.properties["canonical_entity_id"]
        == military.properties["canonical_entity_id"]
    )


def test_osm_geometry_without_center_retains_the_feature():
    row = {
        "type": "way",
        "id": 2,
        "geometry": [{"lat": 40.0, "lon": -74.0}, {"lat": 40.2, "lon": -73.8}],
        "tags": {"name": "Mapped road"},
    }
    value = InfrastructureFeed(HTTP({"elements": [row]})).fetch(VIEW, NOW)[0]
    assert value.position.latitude == pytest.approx(40.1)
    assert len(value.properties["geometry"]["coordinates"]) == 2


def test_overpass_error_remark_is_not_successful_empty_coverage():
    feed = InfrastructureFeed(HTTP({"remark": "runtime error: query timed out", "elements": []}))
    with pytest.raises(ProviderError):
        feed.fetch(VIEW, NOW)
    assert len(feed.http.calls) == 2


def test_orbital_elements_survive_restart_without_another_upstream_request(tmp_path):
    tle = "ISS\n1 25544U 98067A   24287.54791435  .00016717  00000+0  30189-3 0  9997\n2 25544  51.6416  25.9570 0003749  62.4283  58.7756 15.49824920475637\n"
    now = datetime(2024, 10, 13, 12, tzinfo=timezone.utc)
    first = SatelliteFeed(HTTP(text=tle))
    first.configure_cache(tmp_path)
    assert first.fetch(GLOBE, now)
    class Offline(HTTP):
        def text(self, *args, **kwargs):
            raise AssertionError("Fresh orbital elements should be read from disk")
    second = SatelliteFeed(Offline())
    second.configure_cache(tmp_path)
    assert second.fetch(GLOBE, now)
