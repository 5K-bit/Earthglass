"""Exact v1 earthquake collection adapter over the authoritative v2 spatial cache."""

from datetime import UTC, datetime

from ..providers import FeatureCollection, NormalizedFeature, SourceMetadata


def earthquake_collection(engine):
    observations = engine.query(layers=["earthquakes"], limit=5000)["observations"]
    received = max(
        (o["received_at"] for o in observations),
        default=datetime.now(UTC).isoformat(),
    )
    health = next((p["health"] for p in engine.catalog() if p["id"] == "usgs"), {})
    features = []
    for item in observations:
        position, properties = item["position"], item["properties"]
        coordinates = [position["longitude"], position["latitude"]]
        depth = properties.get("depth_m")
        if depth is not None:
            coordinates.append(depth / 1000)
        features.append(
            NormalizedFeature(
                id=item["provenance"]["source_id"],
                geometry={"type": "Point", "coordinates": coordinates},
                properties={
                    **properties,
                    "observed_at": item["observed_at"],
                    "depth_km": depth / 1000 if depth is not None else None,
                },
                provenance={**item["provenance"], "retrieved_at": item["received_at"]},
            )
        )
    return FeatureCollection(
        layer_id="earthquakes",
        features=tuple(features),
        generated_at=received,
        source=SourceMetadata(
            provider="usgs",
            source_url="https://earthquake.usgs.gov/",
            attribution="U.S. Geological Survey (USGS)",
            retrieved_at=received,
        ),
        cache={
            "status": "cache",
            "stale": engine.offline or health.get("state") != "online",
        },
    ).as_geojson()
