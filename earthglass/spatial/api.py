"""FastAPI read adapter. Mutation/control authority is supplied by the OBEOS host."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .models import Viewport


def build_router(engine):
    router = APIRouter(prefix="/api/v2", tags=["spatial"])

    @router.get("/catalog")
    def catalog():
        return {
            "schema_version": "1.0",
            "providers": engine.catalog(),
            "history": engine.history.stats(),
            "offline": engine.offline,
            "network": engine.network_status(),
        }

    @router.get("/observations")
    def observations(
        west: float | None = None,
        south: float | None = None,
        east: float | None = None,
        north: float | None = None,
        layers: str | None = None,
        at: datetime | None = None,
        since: datetime | None = None,
        entity_id: str | None = None,
        limit: int = Query(1000, ge=1, le=5000),
        cursor: int = Query(0, ge=0),
        snapshot_rowid: int | None = Query(None, ge=0),
    ):
        values = (west, south, east, north)
        try:
            if any(value is not None for value in values) and not all(
                value is not None for value in values
            ):
                raise ValueError("All viewport bounds must be provided")
            for instant in (at, since):
                if instant is not None and instant.tzinfo is None:
                    raise ValueError("Time queries require a UTC offset")
            viewport = (
                Viewport(west=west, south=south, east=east, north=north)
                if west is not None
                else None
            )
            return JSONResponse(engine.query(
                viewport=viewport,
                layers=layers.split(",") if layers else None,
                at=at,
                since=since,
                entity_id=entity_id,
                limit=limit,
                cursor=cursor,
                snapshot_rowid=snapshot_rowid,
            ))
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc

    @router.get("/stream")
    async def stream(request: Request, after: int = Query(0, ge=0)):
        try:
            cursor = int(request.headers.get("last-event-id", after))
        except ValueError as exc:
            raise HTTPException(400, detail="Invalid event cursor") from exc

        async def events():
            nonlocal cursor
            while not engine._stop.is_set() and not await request.is_disconnected():
                batch = await asyncio.to_thread(engine.history.changes, cursor)
                if batch["resync"]:
                    yield f"event: resync\ndata: {json.dumps(batch)}\n\n"
                    return
                if batch["changes"]:
                    cursor = batch["sequence"]
                    yield f"id: {cursor}\nevent: observations\ndata: {json.dumps(batch)}\n\n"
                else:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
