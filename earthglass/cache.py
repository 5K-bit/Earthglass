"""Small, persistent, validated cache for normalized provider payloads."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from earthglass.providers import FeatureCollection


class FeatureCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path_for(self, layer_id: str) -> Path:
        if not layer_id or not layer_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("invalid cache layer id")
        return self.directory / f"{layer_id}.json"

    def load(self, layer_id: str) -> FeatureCollection | None:
        path = self.path_for(layer_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != 1:
                return None
            collection = FeatureCollection.from_geojson(payload["collection"])
            if collection.layer_id != layer_id:
                return None
            return collection
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
            return None

    def save(self, collection: FeatureCollection) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.path_for(collection.layer_id)
        serialized = json.dumps(
            {"schema_version": 1, "collection": collection.as_geojson()},
            indent=2,
            sort_keys=True,
        )
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.directory, delete=False
        ) as temporary:
            temporary.write(serialized)
            temporary.flush()
            temp_path = Path(temporary.name)
        temp_path.replace(target)
