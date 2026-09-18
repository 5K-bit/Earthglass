from datetime import timedelta

from ..network import ProviderError
from .base import Feed, ProviderSpec, number, timestamp


class AircraftFeed(Feed):
    source_url = "https://www.adsb.lol/"
    spec = ProviderSpec(
        "adsb",
        "aircraft",
        "Aircraft",
        30,
        "Regional public ADS-B observations, up to 250 nautical miles; incomplete coverage",
        "adsb.lol contributors (ODbL 1.0)",
        transport="polling",
        license_url="https://www.adsb.lol/legal/",
    )

    def fetch(self, viewport, now):
        latitude, longitude = viewport.center
        radius = min(250, max(25, (viewport.north - viewport.south) * 30))
        try:
            data = self.http.json(
                f"https://api.adsb.lol/v2/lat/{latitude:.3f}/lon/{longitude:.3f}/dist/{radius:.0f}"
            )
            return self.from_adsb(data, now, viewport)
        except ProviderError:
            # Public OpenSky state vectors provide an independently sourced fallback.
            self.bounded(viewport, 10)
            data = self.http.json(
                "https://opensky-network.org/api/states/all",
                params={
                    "lamin": viewport.south,
                    "lamax": viewport.north,
                    "lomin": viewport.west,
                    "lomax": viewport.east,
                },
            )
            return self.from_opensky(data, now)

    def from_adsb(self, data, now, viewport):
        source_now = number(data.get("now"), now.timestamp())
        if source_now > 1e12:
            source_now /= 1000

        def parse(row):
            lat, lon = number(row.get("lat")), number(row.get("lon"))
            if lat is None or lon is None:
                return None
            age = number(row.get("seen_pos"), 0)
            altitude = number(row.get("alt_geom"))
            reference = "ellipsoid" if altitude is not None else "barometric"
            altitude = altitude if altitude is not None else number(row.get("alt_baro"))
            heading = number(row.get("track"))
            position = {
                "latitude": lat,
                "longitude": lon,
                "altitude_m": altitude * 0.3048 if altitude is not None else None,
                "altitude_reference": reference,
            }
            observation = self.observation(
                source_id=row["hex"],
                entity_id=f"{'military:' if self.spec.layer == 'military' else ''}icao24:{str(row['hex']).lower()}",
                entity_type="aircraft",
                position=position,
                observed_at=timestamp(source_now) - timedelta(seconds=max(0, age)),
                received_at=now,
                motion={
                    "heading_deg": heading % 360 if heading is not None else None,
                    "speed_mps": number(row.get("gs")) * 0.514444
                    if number(row.get("gs")) is not None
                    else None,
                    "vertical_rate_mps": number(row.get("baro_rate")) * 0.00508
                    if number(row.get("baro_rate")) is not None
                    else None,
                },
                properties={
                    "canonical_entity_id": f"icao24:{str(row['hex']).lower()}",
                    "callsign": str(row.get("flight") or "").strip(),
                    "registration": row.get("r"),
                    "aircraft_type": row.get("t"),
                    "on_ground": row.get("alt_baro") == "ground",
                    "military": self.spec.layer == "military",
                    "coverage": self.spec.coverage,
                },
            )
            return observation if viewport.contains(observation.position) else None

        return self.normalize(data.get("ac", data.get("aircraft", [])), parse)

    def from_opensky(self, data, now):
        def parse(row):
            if row[5] is None or row[6] is None or row[3] is None:
                return None
            observation = self.observation(
                source_id=row[0],
                entity_id=f"icao24:{row[0]}",
                entity_type="aircraft",
                position={
                    "latitude": row[6],
                    "longitude": row[5],
                    "altitude_m": row[13]
                    if len(row) > 13 and row[13] is not None
                    else row[7],
                    "altitude_reference": "ellipsoid"
                    if len(row) > 13 and row[13] is not None
                    else "barometric",
                },
                motion={
                    "heading_deg": row[10],
                    "speed_mps": row[9],
                    "vertical_rate_mps": row[11],
                },
                observed_at=timestamp(row[3]),
                received_at=now,
                properties={
                    "callsign": str(row[1] or "").strip(),
                    "on_ground": row[8],
                    "fallback": True,
                    "coverage": "OpenSky public state vectors; provider terms and partial coverage apply",
                },
            )
            observation.provenance.provider = "opensky"
            observation.provenance.source_url = "https://opensky-network.org/"
            observation.provenance.attribution = (
                "OpenSky Network — Bringing Up OpenSky, IPSN 2014"
            )
            observation.provenance.license_url = (
                "https://opensky-network.org/about/terms-of-use"
            )
            return observation

        return self.normalize(data.get("states") or [], parse)


class MilitaryFeed(AircraftFeed):
    spec = ProviderSpec(
        "adsb_military",
        "military",
        "Public military flights",
        30,
        "Public ADS-B military registry observations only; not complete military activity",
        "adsb.lol contributors (ODbL 1.0)",
        transport="polling",
        license_url="https://www.adsb.lol/legal/",
    )

    def fetch(self, viewport, now):
        return self.from_adsb(
            self.http.json("https://api.adsb.lol/v2/mil"), now, viewport
        )
