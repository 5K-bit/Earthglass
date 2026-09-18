"""Bounded GeoJSON normalization and conservative viewport overlap."""

import math


def normalize_geometry(raw, max_points=600):
    if not isinstance(raw, dict):
        raise ValueError("Missing geometry")
    if not 4 <= max_points <= 2000:
        raise ValueError("Invalid geometry detail bound")
    kind, coordinates = raw.get("type"), raw.get("coordinates")
    if kind not in {"Point", "LineString", "Polygon", "MultiPolygon"}:
        raise ValueError("Unsupported geometry")
    extent = [math.inf, math.inf, -math.inf, -math.inf]

    def point(value):
        if (
            not isinstance(value, (list, tuple))
            or len(value) < 2
            or any(isinstance(v, bool) for v in value[:2])
        ):
            raise ValueError("Invalid coordinate")
        lon, lat = float(value[0]), float(value[1])
        if (
            not math.isfinite(lon)
            or not math.isfinite(lat)
            or not -180 <= lon <= 180
            or not -90 <= lat <= 90
        ):
            raise ValueError("Invalid WGS84 coordinate")
        extent[0] = min(extent[0], lon)
        extent[1] = min(extent[1], lat)
        extent[2] = max(extent[2], lon)
        extent[3] = max(extent[3], lat)
        return [lon, lat]

    def line(values, closed=False):
        if (
            not isinstance(values, list)
            or not (4 if closed else 2) <= len(values) <= 200000
        ):
            raise ValueError("Invalid geometry ring")
        step = max(1, math.ceil((len(values) - 1) / (max_points - 1)))
        result = []
        for index, value in enumerate(values):
            parsed = point(value)
            if index % step == 0 or index == len(values) - 1:
                result.append(parsed)
        if closed:
            if result[-1] != result[0]:
                result.append(result[0])
            if len(result) < 4:
                raise ValueError("Degenerate polygon")
        return result

    def polygon(rings):
        if not isinstance(rings, list) or not rings:
            raise ValueError("Missing polygon rings")
        return [line(ring, True) for ring in rings[:8]]

    if kind == "Point":
        normalized = point(coordinates)
    elif kind == "LineString":
        normalized = line(coordinates)
    elif kind == "Polygon":
        normalized = polygon(coordinates)
    else:
        if not isinstance(coordinates, list):
            raise ValueError("Missing polygons")
        normalized = [polygon(value) for value in coordinates[:8]]
    west, south, east, north = extent
    if not all(math.isfinite(v) for v in extent):
        raise ValueError("Empty geometry")
    if east - west > 180:
        west, east = -180, 180
    bounds = {"west": west, "east": east, "south": south, "north": north}
    return (
        {"type": kind, "coordinates": normalized},
        {"latitude": (south + north) / 2, "longitude": (west + east) / 2},
        bounds,
    )


def overlaps(viewport, bounds):
    if (
        not bounds
        or bounds["south"] > viewport.north
        or bounds["north"] < viewport.south
    ):
        return False
    if viewport.west <= viewport.east:
        return bounds["west"] <= viewport.east and bounds["east"] >= viewport.west
    return bounds["west"] <= viewport.east or bounds["east"] >= viewport.west


def observation_in_view(observation, viewport):
    return viewport.contains(observation.position) or overlaps(
        viewport, observation.properties.get("spatial_bounds")
    )
