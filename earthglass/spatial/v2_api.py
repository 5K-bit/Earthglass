"""Domain-specific V2 read routes over the existing bounded observation store."""

from datetime import UTC, datetime, timedelta
import math

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .models import Viewport
from .network import ProviderError
from .products import envelope, imagery_time


def build_v2_router(engine, tiles, *, on_transit_import=None):
    router = APIRouter(prefix="/api/v2", tags=["planetary-v2"])

    def document(ident):
        entry = engine._entries.get(ident)
        return (
            entry["feed"].document()
            if entry and hasattr(entry["feed"], "document")
            else {}
        )

    def query(request, layers, entity_id=None):
        params = request.query_params
        bounds = [params.get(k) for k in ("west", "south", "east", "north")]
        try:
            viewport = (
                Viewport(
                    **{
                        k: float(v)
                        for k, v in zip(("west", "south", "east", "north"), bounds)
                    }
                )
                if all(v is not None for v in bounds)
                else None
            )
            if any(v is not None for v in bounds) and viewport is None:
                raise ValueError("All four viewport bounds are required")
            at = (
                datetime.fromisoformat(params["at"].replace("Z", "+00:00"))
                if params.get("at")
                else None
            )
            if at is not None and at.tzinfo is None:
                raise ValueError("UTC offset required")
            limit = max(1, min(2000, int(params.get("limit", 500))))
            cursor = max(0, int(params.get("cursor", 0)))
            since = None
            if params.get("maximum_age_hours"):
                hours = float(params["maximum_age_hours"])
                if not 0 < hours <= 168:
                    raise ValueError("Age must be between zero and 168 hours")
                since = (at or datetime.now(UTC)) - timedelta(hours=hours)
            page = engine.query(
                viewport=viewport,
                layers=layers,
                entity_id=entity_id,
                at=at,
                since=since,
                limit=limit,
                cursor=cursor,
                snapshot_rowid=int(params["snapshot_rowid"])
                if params.get("snapshot_rowid")
                else None,
            )
            values = page["observations"] + page.get("volatile_observations", [])
            for field, key, direction in (
                ("minimum_magnitude", "magnitude", 1),
                ("minimum_depth_m", "depth_m", 1),
                ("maximum_depth_m", "depth_m", -1),
            ):
                if field in params:
                    threshold = float(params[field])
                    if not math.isfinite(threshold):
                        raise ValueError("Numeric filters must be finite")
                    values = [
                        o
                        for o in values
                        if isinstance(o["properties"].get(key), (int, float))
                        and direction * o["properties"][key] >= direction * threshold
                    ]
            return envelope(
                engine,
                values,
                layers=layers,
                extra={
                    "next_cursor": page["next_cursor"],
                    "sequence": page["sequence"],
                    "snapshot_rowid": page.get("snapshot_rowid"),
                },
            )
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc))

    @router.get("/system/providers")
    def system_providers():
        return envelope(engine, engine.catalog(), product="provider-health")

    routes = {
        "/mobility/traffic": ["traffic_speeds"],
        "/mobility/traffic/roads": ["traffic", "traffic_speeds"],
        "/mobility/traffic/incidents": ["traffic_incidents"],
        "/mobility/incidents": ["traffic_incidents"],
        "/mobility/cameras": ["cctv"],
        "/mobility/transit/vehicles": ["transit_vehicles"],
        "/mobility/transit/routes": ["transit_routes"],
        "/mobility/routes": ["transit_routes"],
        "/mobility/transit/stops": ["transit_stops"],
        "/aircraft": ["aircraft"],
        "/seismic/events": ["earthquakes"],
        "/fires": ["fires"],
        "/alerts/weather": ["weather_alerts"],
        "/events": ["natural_events"],
        "/aviation/metar": ["aviation_metar"],
        "/aviation/taf": ["aviation_taf"],
        "/aviation/sigmet": ["aviation_sigmet"],
        "/aviation/gairmet": ["aviation_gairmet"],
        "/aviation/pirep": ["aviation_pirep"],
        "/weather/temperature": ["temperature"],
        "/weather/wind": ["wind"],
        "/weather/precipitation": ["precipitation"],
        "/weather/pressure": ["pressure"],
        "/weather/clouds": ["clouds"],
    }

    def endpoint(layers):
        def read(request: Request):
            return query(request, layers)

        return read

    for path, layers in routes.items():
        router.add_api_route(path, endpoint(layers), methods=["GET"])
    for path, layers in {
        "/aircraft/status": ["aircraft"],
        "/seismic/status": ["earthquakes"],
        "/fires/status": ["fires"],
        "/mobility/cameras/status": ["cctv"],
        "/weather/status": ["weather", "temperature"],
    }.items():

        def status_endpoint(selected):
            def status():
                return envelope(
                    engine,
                    [p for p in engine.catalog() if p["layer"] in selected],
                    layers=selected,
                )

            return status

        router.add_api_route(path, status_endpoint(layers), methods=["GET"])

    @router.get("/weather/layers")
    def weather_layers():
        return envelope(
            engine,
            ["temperature", "wind", "precipitation", "pressure", "clouds"],
            layers=["weather", "temperature"],
            product="weather-fields",
        )

    @router.get("/events/categories")
    def categories():
        values = engine.query(layers=["natural_events"], limit=2000)["observations"]
        unique = {
            c["id"]: c
            for o in values
            for c in o["properties"].get("categories", [])
            if isinstance(c, dict) and c.get("id")
        }
        return envelope(engine, list(unique.values()), layers=["natural_events"])

    def detail(layers, prefix=""):
        def read(ident: str, request: Request):
            result = query(request, layers, prefix + ident)
            if not result["data"]:
                raise HTTPException(404, "Object is not in retained local data")
            result["data"] = result["data"][0]
            return result

        return read

    for path, layers, prefix in [
        ("/mobility/cameras/{ident}", ["cctv"], ""),
        ("/mobility/incidents/{ident}", ["traffic_incidents"], ""),
        ("/aircraft/{ident}", ["aircraft"], "icao24:"),
        ("/seismic/events/{ident}", ["earthquakes"], "usgs:"),
        ("/events/{ident}", ["natural_events"], "nasa_eonet:"),
        ("/alerts/weather/{ident}", ["weather_alerts"], "noaa_nws:"),
    ]:
        router.add_api_route(path, detail(layers, prefix), methods=["GET"])

    @router.get("/imagery/catalog")
    @router.get("/imagery/layers")
    def imagery_catalog():
        return envelope(
            engine,
            document("nasa_gibs").get("data", []),
            layers=["imagery"],
            product="imagery-catalog",
        )

    @router.get("/imagery/frame/{product}")
    def imagery_frame(product: str, at: str | None = None):
        item = next(
            (
                v
                for v in document("nasa_gibs").get("data", [])
                if v["id"] == product and v.get("available")
            ),
            None,
        )
        if not item:
            raise HTTPException(404, "Imagery product unavailable")
        try:
            return {
                "product": product,
                "time": imagery_time(item, at),
                "attribution": item["attribution"],
            }
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @router.get("/imagery/status")
    def imagery_status():
        return envelope(
            engine,
            [p for p in engine.catalog() if p["layer"] == "imagery"],
            layers=["imagery"],
        )

    @router.get("/imagery/tiles/{product}/{instant}/{z}/{x}/{y}")
    def imagery_tile(product: str, instant: str, z: int, x: int, y: int):
        products = document("nasa_gibs").get("data", [])
        item = next(
            (v for v in products if v["id"] == product and v.get("available")), None
        )
        if not item:
            raise HTTPException(
                404,
                "Imagery product unavailable; enable NASA imagery to load its catalog",
            )
        if (
            not 0 <= z <= item["maximum_level"]
            or not 0 <= x < 2**z
            or not 0 <= y < 2**z
        ):
            raise HTTPException(422, "Tile outside imagery matrix")
        try:
            at = imagery_time(item, None if instant == "latest" else instant)
            key = f"{product}/{at}/{z}/{x}/{y}"
            url = f"https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/{item['source_layer']}/default/{at}/{item['matrix_set']}/{z}/{y}/{x}.{item['extension']}"
            body, kind, cached = tiles.fetch(engine.http, key, url)
            return Response(
                body,
                media_type=kind,
                headers={
                    "Cache-Control": "private, max-age=3600",
                    "X-Earth-Source": item["provider"],
                    "X-Earth-Time": at,
                    "X-Earth-Cache": "hit" if cached else "miss",
                },
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except ProviderError as exc:
            raise HTTPException(503, {"code": exc.code, "message": str(exc)})

    @router.get("/space-weather/current")
    def space_current():
        data = document("noaa_swpc").get("data", {})
        return envelope(
            engine,
            {
                name: {**value, "records": value.get("records", [])[-1:]}
                for name, value in data.items()
                if name != "alerts"
            },
            layers=["space_weather"],
        )

    @router.get("/space-weather/history")
    def space_history():
        return envelope(
            engine, document("noaa_swpc").get("data", {}), layers=["space_weather"]
        )

    @router.get("/space-weather/alerts")
    def space_alerts():
        return envelope(
            engine,
            document("noaa_swpc").get("data", {}).get("alerts", {}),
            layers=["space_weather"],
        )

    @router.get("/mobility/status")
    @router.get("/mobility/providers")
    @router.get("/mobility/traffic/status")
    @router.get("/mobility/transit/status")
    def mobility_status():
        layers = [
            "traffic",
            "traffic_speeds",
            "traffic_incidents",
            "transit_vehicles",
            "transit_routes",
            "transit_stops",
            "transit_alerts",
            "cctv",
        ]
        return envelope(
            engine, [p for p in engine.catalog() if p["layer"] in layers], layers=layers
        )

    @router.get("/mobility/transit/alerts")
    @router.get("/mobility/alerts")
    def transit_alerts(route_id: str | None = None):
        values = [
            {**alert, "provider": entry["feed"].spec.id}
            for entry in engine._entries.values()
            if entry["feed"].spec.layer in {"transit_alerts", "transit_vehicles"}
            and hasattr(entry["feed"], "document")
            for alert in entry["feed"].document().get("data", {}).get("alerts", [])
            if route_id is None or route_id in alert.get("routes", [])
        ]
        return envelope(
            engine, values[:1000], layers=["transit_alerts", "transit_vehicles"]
        )

    @router.get("/mobility/transit/trip-updates")
    def trip_updates(route_id: str | None = None):
        values = [
            {**trip, "provider": entry["feed"].spec.id}
            for entry in engine._entries.values()
            if entry["feed"].spec.layer == "transit_vehicles"
            and hasattr(entry["feed"], "document")
            for trip in entry["feed"].document().get("data", {}).get("trip_updates", [])
            if route_id is None or trip.get("route_id") == route_id
        ]
        return envelope(engine, values[:1000], layers=["transit_vehicles"])

    @router.get("/mobility/transit/imports")
    def transit_imports():
        entry = engine._entries.get("local_gtfs")
        return envelope(
            engine,
            [
                {k: v for k, v in value.items() if k not in {"observations", "routes"}}
                for value in entry["feed"].documents()
            ]
            if entry
            else [],
            layers=["transit_routes", "transit_stops"],
        )

    @router.post("/mobility/transit/import")
    async def transit_import(
        request: Request, agency: str, source_url: str, attribution: str
    ):
        import asyncio
        import zipfile

        from ..mobility.static_gtfs import import_gtfs

        entry = engine._entries.get("local_gtfs")
        if not entry:
            raise HTTPException(503, "Static transit importer unavailable")
        body = await request.body()
        if len(body) > 12 * 1024 * 1024:
            raise HTTPException(
                413,
                "Desktop import limit is 12 MiB; use the local import command for larger archives",
            )
        try:
            document_ = await asyncio.to_thread(
                import_gtfs,
                body,
                agency=agency,
                source_url=source_url,
                attribution=attribution,
            )
            result = await asyncio.to_thread(entry["feed"].install, document_)
            if on_transit_import:
                await asyncio.to_thread(on_transit_import)
            else:
                engine.enable("transit_routes")
                engine.enable("transit_stops")
            for ident in ("local_gtfs", "local_gtfs_stops"):
                if ident in engine._entries:
                    engine._entries[ident]["next"] = 0
            return envelope(engine, result, layers=["transit_routes", "transit_stops"])
        except (ValueError, KeyError, zipfile.BadZipFile) as exc:
            raise HTTPException(422, str(exc))

    @router.get("/orbits/groups")
    def orbit_groups():
        return envelope(
            engine,
            [
                entry["feed"].status()
                for entry in engine._entries.values()
                if hasattr(entry["feed"], "project")
            ],
            layers=["satellites"],
        )

    @router.get("/orbits/objects")
    def orbit_objects(
        request: Request,
        group: str | None = None,
        at: str | None = None,
        limit: int = 500,
    ):
        try:
            instant = (
                datetime.fromisoformat(at.replace("Z", "+00:00"))
                if at
                else datetime.now(UTC)
            )
            if instant.tzinfo is None:
                raise ValueError("UTC offset required")
            bounds = {
                k: request.query_params.get(k)
                for k in ("west", "south", "east", "north")
            }
            viewport = (
                Viewport(**bounds)
                if any(v is not None for v in bounds.values())
                else None
            )
            values = []
            for entry in engine._entries.values():
                feed = entry["feed"]
                if hasattr(feed, "project") and (group is None or feed.group == group):
                    values.extend(
                        o.wire()
                        for o in feed.project(
                            instant, viewport=viewport, limit=max(1, min(2000, limit))
                        )
                    )
            return envelope(
                engine,
                values[: max(1, min(2000, limit))],
                layers=["satellites"],
                extra={"at": instant.isoformat(), "prediction": True},
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @router.get("/orbits/{norad}")
    @router.get("/orbits/{norad}/track")
    @router.get("/orbits/objects/{norad}")
    @router.get("/orbits/objects/{norad}/track")
    def orbit_object(
        norad: int,
        request: Request,
        at: str | None = None,
        minutes: int = 90,
        step_seconds: int = 60,
    ):
        try:
            instant = (
                datetime.fromisoformat(at.replace("Z", "+00:00"))
                if at
                else datetime.now(UTC)
            )
            if instant.tzinfo is None:
                raise ValueError("UTC offset required")
            if not 1 <= minutes <= 180 or not 30 <= step_seconds <= 600:
                raise ValueError("Track range 1–180 minutes; step 30–600 seconds")
            values = []
            for entry in engine._entries.values():
                feed = entry["feed"]
                if not hasattr(feed, "project"):
                    continue
                first = feed.project(instant, norad=norad, limit=1)
                if not first:
                    continue
                if request.url.path.endswith("/track"):
                    values = [
                        o.wire()
                        for seconds in range(0, minutes * 60 + 1, step_seconds)
                        for o in feed.project(
                            instant + timedelta(seconds=seconds), norad=norad, limit=1
                        )
                    ]
                else:
                    values = [first[0].wire()]
                break
            if not values:
                raise HTTPException(
                    404, "No valid local elements for this object and time"
                )
            return envelope(
                engine,
                values if request.url.path.endswith("/track") else values[0],
                layers=["satellites"],
                extra={"prediction": True},
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    return router
