"""Private API; owner authority is supplied only by the native host or configured gateway."""

import asyncio
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .models import (
    DeviceRegistration,
    DeviceUpdate,
    PresenceSettings,
    ViewerRegistration,
)
from .store import PresenceDenied, digest
from .traccar import normalize_forward


def build_presence_app(store, *, owner_auth=None, require_tls=True):
    @asynccontextmanager
    async def lifespan(app):
        async def maintenance():
            while True:
                await asyncio.sleep(60)
                await asyncio.to_thread(store.prune)

        task = asyncio.create_task(maintenance())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app = FastAPI(
        title="OBEOS Private Presence",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.store = store
    last_prune = [time.monotonic()]

    @app.middleware("http")
    async def private_boundary(request, call_next):
        if require_tls and request.url.scheme != "https":
            return JSONResponse(
                {"error": "encrypted_transport_required"}, status_code=403
            )
        peer = request.client.host if request.client else "unknown"
        if not store.rate_limit("peer:" + digest(peer), 300):
            return JSONResponse({"error": "rate_limited"}, status_code=429)
        if request.method not in {"GET", "HEAD"}:
            length = request.headers.get("content-length", "0")
            if not length.isdigit() or int(length) > 32768:
                return JSONResponse({"error": "request_too_large"}, status_code=413)
            # Stream the body with a bound even when Content-Length is absent.
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 32768:
                    return JSONResponse({"error": "request_too_large"}, status_code=413)
            request._body = bytes(body)
        if time.monotonic() - last_prune[0] >= 60:
            last_prune[0] = time.monotonic()
            await asyncio.to_thread(store.prune)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(PresenceDenied)
    async def denied(request, exc):
        return JSONResponse({"error": "presence_access_denied"}, status_code=403)

    def principal(request: Request):
        if owner_auth and owner_auth(request):
            return {"kind": "owner", "subject": "local-operator", "scope": {}}
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        actor = store.authenticate(token)
        if not actor:
            store.audit("unknown", "authenticate", outcome="denied")
            raise HTTPException(401, "Private authentication required")
        if not store.rate_limit("credential:" + actor["id"], 120):
            raise HTTPException(429, "Credential rate limit reached")
        return actor

    def viewer(actor=Depends(principal)):
        if actor["kind"] not in {"owner", "viewer"}:
            raise HTTPException(403, "Viewer authorization required")
        return actor

    def owner(actor=Depends(principal)):
        if actor["kind"] != "owner":
            raise HTTPException(403, "Owner authorization required")
        return actor

    def instant(value):
        if value is None:
            return None
        try:
            at = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if at.tzinfo is None:
                raise ValueError("UTC offset required")
            return at.astimezone(UTC)
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    def checked(action):
        try:
            return action()
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    prefix = "/v2/presence"

    @app.get(prefix + "/settings")
    def settings(actor=Depends(viewer)):
        return {**store.settings(), "role": actor["kind"]}

    @app.patch(prefix + "/settings")
    def configure(payload: PresenceSettings, actor=Depends(owner)):
        result = checked(lambda: store.configure(payload))
        store.audit(actor["subject"], "configure")
        return result

    @app.get(prefix + "/devices")
    def devices(actor=Depends(owner)):
        return {
            "data": [store.device(d["device_id"]) for d in store.list_current(actor)]
        }

    @app.post(prefix + "/devices", status_code=201)
    def register(payload: DeviceRegistration, actor=Depends(owner)):
        result = checked(lambda: store.register(payload, actor["subject"]))
        store.audit(actor["subject"], "register", payload.device_id)
        return result

    @app.patch(prefix + "/devices/{device_id}")
    def update(device_id: str, payload: DeviceUpdate, actor=Depends(owner)):
        result = checked(lambda: store.update(device_id, payload))
        store.audit(actor["subject"], "update", device_id)
        return result

    @app.delete(prefix + "/devices/{device_id}")
    def delete(device_id: str, actor=Depends(owner)):
        store.delete(device_id)
        store.audit(actor["subject"], "delete", device_id)
        return {"deleted": True}

    @app.post(prefix + "/devices/{device_id}/rotate")
    def rotate(device_id: str, actor=Depends(owner)):
        result = store.rotate_device(device_id)
        store.audit(actor["subject"], "rotate", device_id)
        return result

    @app.get(prefix + "/viewers")
    def viewers(actor=Depends(owner)):
        return {"data": store.viewers()}

    @app.post(prefix + "/viewers", status_code=201)
    def add_viewer(payload: ViewerRegistration, actor=Depends(owner)):
        result = checked(lambda: store.add_viewer(payload))
        store.audit(actor["subject"], "grant_viewer")
        return result

    @app.delete(prefix + "/viewers/{credential_id}")
    def revoke(credential_id: str, actor=Depends(owner)):
        store.revoke(credential_id)
        store.audit(actor["subject"], "revoke_credential")
        return {"revoked": True}

    @app.get(prefix + "/audit")
    def audit(actor=Depends(owner)):
        return {"data": store.audit_entries()}

    @app.post(prefix + "/ingest/traccar")
    def ingest(payload: dict, actor=Depends(principal)):
        if actor["kind"] != "device":
            raise HTTPException(403, "Device-specific credential required")
        device = store.device(actor["subject"])
        result = checked(
            lambda: store.ingest(
                actor["subject"], normalize_forward(payload, device["traccar_id"])
            )
        )
        store.audit(actor["subject"], "position_received", actor["subject"])
        return result

    @app.get(prefix)
    def current(at: str | None = None, actor=Depends(viewer)):
        result = store.list_current(actor, instant(at))
        store.audit(actor["subject"], "read_current")
        return {
            "schema_version": "2.0",
            "data": result,
            "private": True,
            "enabled": store.settings()["enabled"],
        }

    @app.get(prefix + "/{device_id}/history")
    @app.get(prefix + "/{device_id}/trail")
    def history(
        device_id: str,
        start: str | None = None,
        end: str | None = None,
        cursor: int = 0,
        limit: int = 500,
        actor=Depends(viewer),
    ):
        finish = instant(end) or datetime.now(UTC)
        begin = instant(start) or finish - timedelta(hours=1)
        result = checked(
            lambda: store.history(
                device_id, actor, begin, finish, cursor=cursor, limit=limit
            )
        )
        store.audit(actor["subject"], "read_history", device_id)
        return {"schema_version": "2.0", **result, "private": True}

    @app.get(prefix + "/{device_id}/status")
    @app.get(prefix + "/{device_id}")
    def detail(device_id: str, at: str | None = None, actor=Depends(viewer)):
        result = store.current(device_id, actor, instant(at))
        store.audit(actor["subject"], "read_device", device_id)
        return result

    return app
