"""Server-held on-air state for the broadcast program output.

The operator (control room) writes the current shot and product here; every program
output (an OBS Browser Source, a second machine, a browser tab) reads it. This replaces
same-browser BroadcastChannel sync, which cannot reach OBS.

Writes are protected: with ``EARTHGLASS_CONTROL_TOKEN`` set they need that token in the
``X-Control-Token`` header; with no token configured only loopback clients may write.
"""

from __future__ import annotations

import hmac
import json
import os
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from earthglass.providers import isoformat, utc_now

IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


class ProgramUpdate(BaseModel):
    scene: str
    field: str


class ProgramState:
    def __init__(
        self,
        path: Path | None = None,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.path = path
        self.clock = clock
        self._lock = Lock()
        self._state: dict[str, Any] = {"scene": None, "field": None, "revision": 0, "updated_at": None}
        # Staged next shot. Held in memory only: a restart never leaves something armed.
        self._preview: dict[str, str] | None = None
        # Persistence health, reported to the operator. In-memory state stays authoritative
        # for the live program, but a failed save must never be silent: after a restart the
        # program would revert to an older shot.
        self._persistence: dict[str, Any] = {"ok": True, "error": None, "failed_at": None, "recovered_from": None}
        self._load()

    def _load(self) -> None:
        if self.path is None:
            return
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                IDENTIFIER.match(data["scene"])
                and IDENTIFIER.match(data["field"])
                and isinstance(data["revision"], int)
            ):
                self._state = {
                    "scene": data["scene"],
                    "field": data["field"],
                    "revision": data["revision"],
                    "updated_at": data.get("updated_at"),
                }
            else:
                raise ValueError("saved program state has invalid fields")
        except (OSError, KeyError, ValueError, TypeError) as exc:
            # No usable saved state: start unset, keep the bad file for inspection, and say so.
            self._persistence["recovered_from"] = f"{type(exc).__name__}: {exc}"
            try:
                self.path.replace(self.path.with_name(self.path.name + ".corrupt"))
            except OSError:
                pass

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._view()

    def _view(self) -> dict[str, Any]:
        return {
            **self._state,
            "preview": self._preview,
            "persistence": dict(self._persistence),
            "server_time": isoformat(self.clock()),
        }

    def stage(self, scene: str, field: str) -> dict[str, Any]:
        """Arm the next shot without changing what is on air."""

        if not IDENTIFIER.match(scene) or not IDENTIFIER.match(field):
            raise ValueError("scene and field must be short lowercase identifiers")
        with self._lock:
            self._preview = {"scene": scene, "field": field}
            return self._view()

    def take(self, scene: str, field: str) -> dict[str, Any]:
        """Put the staged shot on air. The caller names what it believes is staged; a mismatch is refused."""

        with self._lock:
            if self._preview is None:
                raise LookupError("nothing is staged")
            if self._preview != {"scene": scene, "field": field}:
                raise LookupError("the staged shot changed; review it and take again")
            self._state = {
                "scene": scene,
                "field": field,
                "revision": self._state["revision"] + 1,
                "updated_at": isoformat(self.clock()),
            }
            self._persist()
            return self._view()

    def update(self, scene: str, field: str) -> dict[str, Any]:
        if not IDENTIFIER.match(scene) or not IDENTIFIER.match(field):
            raise ValueError("scene and field must be short lowercase identifiers")
        with self._lock:
            self._state = {
                "scene": scene,
                "field": field,
                "revision": self._state["revision"] + 1,
                "updated_at": isoformat(self.clock()),
            }
            self._persist()
            return self._view()

    def _persist(self) -> None:
        if self.path is None:
            return
        temp: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=self.path.parent, delete=False) as handle:
                temp = Path(handle.name)
                handle.write(json.dumps(self._state).encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            temp.replace(self.path)
            self._persistence = {"ok": True, "error": None, "failed_at": None, "recovered_from": None}
        except OSError as exc:
            # The live in-memory state stays authoritative, but the failure is reported.
            self._persistence = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "failed_at": isoformat(self.clock()),
                "recovered_from": self._persistence.get("recovered_from"),
            }
            if temp is not None:
                try:
                    temp.unlink()
                except OSError:
                    pass

    def router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/api/broadcast/program")
        def read_program() -> dict[str, Any]:
            return self.snapshot()

        def authorize(request: Request, supplied: str | None) -> None:
            token = os.getenv("EARTHGLASS_CONTROL_TOKEN", "")
            if token:
                if not supplied or not hmac.compare_digest(supplied, token):
                    raise HTTPException(401, "Control token required")
            elif (request.client.host if request.client else "") not in LOOPBACK_HOSTS:
                raise HTTPException(403, "Program control is limited to this machine unless a control token is set")

        @router.post("/api/broadcast/program")
        def write_program(
            update: ProgramUpdate,
            request: Request,
            x_control_token: str | None = Header(default=None),
        ) -> dict[str, Any]:
            """Direct cut to air, skipping preview. Prefer preview then take."""

            authorize(request, x_control_token)
            try:
                return self.update(update.scene, update.field)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc

        @router.post("/api/broadcast/preview")
        def write_preview(
            update: ProgramUpdate,
            request: Request,
            x_control_token: str | None = Header(default=None),
        ) -> dict[str, Any]:
            authorize(request, x_control_token)
            try:
                return self.stage(update.scene, update.field)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc

        @router.post("/api/broadcast/take")
        def take_preview(
            update: ProgramUpdate,
            request: Request,
            x_control_token: str | None = Header(default=None),
        ) -> dict[str, Any]:
            authorize(request, x_control_token)
            try:
                return self.take(update.scene, update.field)
            except LookupError as exc:
                raise HTTPException(409, str(exc)) from exc

        return router
