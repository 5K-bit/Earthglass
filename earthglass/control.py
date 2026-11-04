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
        self._load()

    def _load(self) -> None:
        if self.path is None:
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
        except (OSError, KeyError, ValueError, TypeError):
            pass  # no usable saved state: start unset

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {**self._state, "server_time": isoformat(self.clock())}

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
            return {**self._state, "server_time": isoformat(self.clock())}

    def _persist(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=self.path.parent, delete=False) as handle:
                handle.write(json.dumps(self._state).encode("utf-8"))
                temp = Path(handle.name)
            temp.replace(self.path)
        except OSError:
            pass  # the live in-memory state stays authoritative

    def router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/api/broadcast/program")
        def read_program() -> dict[str, Any]:
            return self.snapshot()

        @router.post("/api/broadcast/program")
        def write_program(
            update: ProgramUpdate,
            request: Request,
            x_control_token: str | None = Header(default=None),
        ) -> dict[str, Any]:
            token = os.getenv("EARTHGLASS_CONTROL_TOKEN", "")
            if token:
                if not x_control_token or not hmac.compare_digest(x_control_token, token):
                    raise HTTPException(401, "Control token required")
            elif (request.client.host if request.client else "") not in LOOPBACK_HOSTS:
                raise HTTPException(403, "Program control is limited to this machine unless a control token is set")
            try:
                return self.update(update.scene, update.field)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc

        return router
