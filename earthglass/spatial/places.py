"""Offline city search; search text never leaves the local process."""
import gzip
import json
import unicodedata
from functools import lru_cache
from pathlib import Path


def normalized(value):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c)).split())


@lru_cache(maxsize=1)
def cities():
    with gzip.open(Path(__file__).with_name("data") / "cities15000.json.gz", "rt", encoding="utf-8") as stream:
        raw = stream.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("City index exceeds its bound")
    values = json.loads(raw)["cities"]
    # The label is query-independent, so it is normalized once here rather than
    # 50,000 times per search.
    return [
        (
            value,
            {normalized(n) for n in [value["name"], *value["aliases"]]},
            normalized(value["name"] + ", " + value["country"]),
        )
        for value in values[:50000]
    ]


@lru_cache(maxsize=64)
def search_places(query, limit=20):
    text = normalized(query)
    if len(text) < 2:
        return []
    matches = []
    for city, names, label in cities():
        rank = 0 if text in names or text == label else 1 if any(n.startswith(text) for n in names) else 2 if text in label else None
        if rank is not None:
            matches.append((rank, -city["population"], city["name"], city))
    matches.sort(key=lambda row: row[:3])
    return [{"label": city["name"] + ", " + city["country"], "latitude": city["latitude"], "longitude": city["longitude"], "kind": "place", "source_url": "https://www.geonames.org/" + city["id"], "attribution": "GeoNames · CC BY 4.0"} for _, _, _, city in matches[:max(1, min(50, limit))]]
