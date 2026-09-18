"""Isolated private SQLite store, revocable credentials, ACLs and rolling retention."""

import hashlib
import json
import secrets
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import PresenceSettings


def utc_now():
    return datetime.now(UTC)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class PresenceDenied(Exception):
    pass


class PresenceStore:
    def __init__(self, path, *, max_positions=500000):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._closed = False
        self.max_positions = max_positions
        self._con = sqlite3.connect(path, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._con.executescript("""
        PRAGMA foreign_keys=ON;
        PRAGMA secure_delete=ON;
        CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY,owner TEXT NOT NULL,label TEXT NOT NULL,traccar_id TEXT NOT NULL UNIQUE,enabled INTEGER NOT NULL,retention INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS credentials(hash TEXT PRIMARY KEY,id TEXT UNIQUE NOT NULL,kind TEXT NOT NULL,subject TEXT NOT NULL,label TEXT NOT NULL,scope TEXT NOT NULL,expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS current(device TEXT PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,recorded REAL NOT NULL,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS positions(id INTEGER PRIMARY KEY AUTOINCREMENT,device TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,fingerprint TEXT UNIQUE NOT NULL,recorded REAL NOT NULL,payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS presence_time ON positions(device,recorded,id);
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,at TEXT NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,device TEXT,outcome TEXT NOT NULL);
        """)
        self._con.execute(
            "INSERT OR IGNORE INTO settings VALUES(1,?)",
            (PresenceSettings().model_dump_json(),),
        )
        self._con.commit()
        self._rate = {}
        self.prune()

    def settings(self):
        with self._lock:
            return json.loads(
                self._con.execute("SELECT value FROM settings WHERE id=1").fetchone()[0]
            )

    def configure(self, settings):
        if not settings.live_seconds < settings.recent_seconds < settings.stale_seconds:
            raise ValueError("Presence age thresholds must increase")
        with self._lock, self._con:
            self._con.execute(
                "UPDATE settings SET value=? WHERE id=1", (settings.model_dump_json(),)
            )
        return self.settings()

    def audit(self, actor, action, device=None, outcome="ok"):
        with self._lock, self._con:
            self._con.execute(
                "INSERT INTO audit(at,actor,action,device,outcome) VALUES(?,?,?,?,?)",
                (utc_now().isoformat(), actor[:100], action[:100], device, outcome),
            )
            self._con.execute(
                "DELETE FROM audit WHERE id <= (SELECT coalesce(max(id),0)-10000 FROM audit)"
            )

    def rate_limit(self, key, limit=120):
        now = time.monotonic()
        with self._lock:
            if len(self._rate) > 2048:
                self._rate = {k: v for k, v in self._rate.items() if v[0] > now}
            until, count = self._rate.get(key, (now + 60, 0))
            if until <= now:
                until, count = now + 60, 0
            if count >= limit:
                return False
            if key not in self._rate and len(self._rate) >= 4096:
                return False
            self._rate[key] = (until, count + 1)
            return True

    def _credential(self, kind, subject, label, scope, days=366):
        token = secrets.token_urlsafe(32)
        ident = secrets.token_hex(12)
        self._con.execute(
            "INSERT INTO credentials VALUES(?,?,?,?,?,?,?)",
            (
                digest(token),
                ident,
                kind,
                subject,
                label,
                json.dumps(scope),
                (utc_now() + timedelta(days=days)).timestamp(),
            ),
        )
        return {"credential_id": ident, "token": token, "expires_days": days}

    def authenticate(self, token):
        if not token or len(token) > 200:
            return None
        with self._lock:
            row = self._con.execute(
                "SELECT id,kind,subject,label,scope,expires FROM credentials WHERE hash=?",
                (digest(token),),
            ).fetchone()
        if not row or row["expires"] < time.time():
            return None
        return {**dict(row), "scope": json.loads(row["scope"])}

    def register(self, model, owner="local-operator"):
        with self._lock, self._con:
            if self._con.execute("SELECT count(*) FROM devices").fetchone()[0] >= 100:
                raise ValueError("Device limit reached")
            try:
                self._con.execute(
                    "INSERT INTO devices VALUES(?,?,?,?,?,?)",
                    (
                        model.device_id,
                        owner,
                        model.label,
                        model.traccar_id,
                        int(model.tracking_enabled),
                        model.retention_days,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    "Device or Traccar identifier already registered"
                ) from exc
            credential = self._credential("device", model.device_id, model.label, {})
        return {**self.device(model.device_id), **credential}

    def device(self, ident):
        with self._lock:
            row = self._con.execute(
                "SELECT * FROM devices WHERE id=?", (ident,)
            ).fetchone()
        if not row:
            raise PresenceDenied("Unknown or unavailable device")
        return {
            "device_id": row["id"],
            "owner_id": row["owner"],
            "label": row["label"],
            "traccar_id": row["traccar_id"],
            "tracking_enabled": bool(row["enabled"]),
            "retention_days": row["retention"],
        }

    def update(self, ident, model):
        self.device(ident)
        fields = {
            "label": "label",
            "tracking_enabled": "enabled",
            "retention_days": "retention",
        }
        with self._lock, self._con:
            for key, value in model.model_dump(exclude_unset=True).items():
                if value is None:
                    raise ValueError("Device settings cannot be null")
                self._con.execute(
                    "UPDATE devices SET " + fields[key] + "=? WHERE id=?",
                    (value, ident),
                )
        self.prune()
        return self.device(ident)

    def delete(self, ident):
        with self._lock, self._con:
            self._con.execute(
                "DELETE FROM credentials WHERE kind='device' AND subject=?", (ident,)
            )
            self._con.execute("DELETE FROM devices WHERE id=?", (ident,))

    def rotate_device(self, ident):
        device = self.device(ident)
        with self._lock, self._con:
            self._con.execute(
                "DELETE FROM credentials WHERE kind='device' AND subject=?", (ident,)
            )
            return self._credential("device", ident, device["label"], {})

    def add_viewer(self, model):
        for ident in model.devices:
            self.device(ident)
        with self._lock, self._con:
            if (
                self._con.execute(
                    "SELECT count(*) FROM credentials WHERE kind='viewer'"
                ).fetchone()[0]
                >= 100
            ):
                raise ValueError("Viewer limit reached")
            return self._credential(
                "viewer",
                secrets.token_hex(12),
                model.label,
                {
                    "devices": list(dict.fromkeys(model.devices)),
                    "history": model.history,
                    "battery": model.battery,
                },
                model.expires_days,
            )

    def revoke(self, ident):
        with self._lock, self._con:
            self._con.execute("DELETE FROM credentials WHERE id=?", (ident,))

    def viewers(self):
        with self._lock:
            rows = self._con.execute(
                "SELECT id,label,scope,expires FROM credentials WHERE kind='viewer'"
            ).fetchall()
        return [{**dict(row), "scope": json.loads(row["scope"])} for row in rows]

    def allowed(self, principal, ident, *, history=False):
        self.device(ident)
        if principal["kind"] == "owner":
            return
        scope = principal.get("scope", {})
        if (
            principal["kind"] != "viewer"
            or ident not in scope.get("devices", [])
            or (history and not scope.get("history"))
        ):
            raise PresenceDenied("Access not granted")

    def ingest(self, ident, position):
        device = self.device(ident)
        if not self.settings()["enabled"] or not device["tracking_enabled"]:
            raise PresenceDenied("Tracking disabled")
        now = utc_now()
        recorded = position.recorded_at
        if recorded > now + timedelta(minutes=5):
            raise ValueError("Position is in the future")
        if recorded < now - timedelta(days=max(device["retention_days"], 1)):
            raise ValueError("Position is outside retention")
        payload = {
            **position.model_dump(mode="json"),
            "device_id": ident,
            "owner_id": device["owner_id"],
            "tracking_provider": "traccar",
            "received_at": now.isoformat(),
        }
        encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False)
        fingerprint = digest(ident + position.model_dump_json())
        with self._lock, self._con:
            if device["retention_days"]:
                count = self._con.execute("SELECT count(*) FROM positions").fetchone()[
                    0
                ]
                if (
                    count >= self.max_positions
                    and not self._con.execute(
                        "SELECT 1 FROM positions WHERE fingerprint=?", (fingerprint,)
                    ).fetchone()
                ):
                    raise ValueError("Private history quota reached; review retention")
                self._con.execute(
                    "INSERT OR IGNORE INTO positions(device,fingerprint,recorded,payload) VALUES(?,?,?,?)",
                    (ident, fingerprint, recorded.timestamp(), encoded),
                )
            self._con.execute(
                "INSERT INTO current VALUES(?,?,?) ON CONFLICT(device) DO UPDATE SET recorded=excluded.recorded,payload=excluded.payload WHERE excluded.recorded>current.recorded",
                (ident, recorded.timestamp(), encoded),
            )
        return {"accepted": True, "device_id": ident}

    def _redact(self, payload, principal):
        value = dict(payload)
        if principal["kind"] != "owner":
            value.pop("owner_id", None)
            if not principal.get("scope", {}).get("battery"):
                value.pop("battery_percent", None)
        return value

    def current(self, ident, principal, at=None):
        self.allowed(principal, ident, history=at is not None)
        device = self.device(ident)
        with self._lock:
            if at:
                row = self._con.execute(
                    "SELECT payload FROM positions WHERE device=? AND recorded<=? ORDER BY recorded DESC,id DESC LIMIT 1",
                    (ident, at.timestamp()),
                ).fetchone()
            else:
                row = self._con.execute(
                    "SELECT payload FROM current WHERE device=?", (ident,)
                ).fetchone()
        position = self._redact(json.loads(row[0]), principal) if row else None
        age = (
            max(
                0,
                (
                    utc_now() - datetime.fromisoformat(position["recorded_at"])
                ).total_seconds(),
            )
            if position
            else None
        )
        settings = self.settings()
        status = (
            "unknown"
            if age is None
            else "live"
            if age <= settings["live_seconds"]
            else "recent"
            if age <= settings["recent_seconds"]
            else "stale"
            if age <= settings["stale_seconds"]
            else "offline"
        )
        if not settings["enabled"] or not device["tracking_enabled"]:
            status = "offline" if position else "unknown"
        return {
            "device_id": ident,
            "label": device["label"],
            "tracking_enabled": device["tracking_enabled"],
            "status": status,
            "age_seconds": age,
            "position": position,
            "historical": at is not None,
            "retention_days": device["retention_days"],
            "permissions": {
                "history": principal["kind"] == "owner"
                or bool(principal.get("scope", {}).get("history"))
            },
        }

    def list_current(self, principal, at=None):
        with self._lock:
            ids = [
                row[0]
                for row in self._con.execute("SELECT id FROM devices ORDER BY label")
            ]
        return [
            self.current(ident, principal, at)
            for ident in ids
            if principal["kind"] == "owner"
            or ident in principal.get("scope", {}).get("devices", [])
        ]

    def history(self, ident, principal, start, end, *, cursor=0, limit=500):
        self.allowed(principal, ident, history=True)
        if start > end or end - start > timedelta(days=366):
            raise ValueError("History range must be ordered and at most 366 days")
        limit = max(1, min(2000, limit))
        with self._lock:
            rows = self._con.execute(
                "SELECT id,payload FROM positions WHERE device=? AND recorded>=? AND recorded<=? AND id>? ORDER BY id LIMIT ?",
                (ident, start.timestamp(), end.timestamp(), max(0, cursor), limit + 1),
            ).fetchall()
        return {
            "data": [
                self._redact(json.loads(row["payload"]), principal)
                for row in rows[:limit]
            ],
            "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None,
        }

    def prune(self):
        with self._lock, self._con:
            for row in self._con.execute("SELECT id,retention FROM devices").fetchall():
                cutoff = time.time() - max(row["retention"], 1) * 86400
                self._con.execute(
                    "DELETE FROM positions WHERE device=? AND (?=0 OR recorded<?)",
                    (row["id"], row["retention"], cutoff),
                )
                self._con.execute(
                    "DELETE FROM current WHERE device=? AND recorded<?",
                    (row["id"], cutoff),
                )
            self._con.execute("DELETE FROM credentials WHERE expires<?", (time.time(),))

    def audit_entries(self):
        with self._lock:
            return [
                dict(row)
                for row in self._con.execute(
                    "SELECT * FROM audit ORDER BY id DESC LIMIT 200"
                )
            ]

    def close(self):
        with self._lock:
            if not self._closed:
                self._closed = True
                self._con.close()
