"""Bounded SQLite observation history with replay and resumable change cursors."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from .models import Observation, Viewport


class SpatialHistory:
    def __init__(self, path: Path, *, retention_days=7, quota_bytes=5 * 1024**3):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        self.quota_bytes = quota_bytes
        self._lock = threading.RLock()
        self._query_cache = OrderedDict()
        self._revision = 0
        self._con = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self._con.row_factory = sqlite3.Row
        self._con.executescript("""
            PRAGMA auto_vacuum=INCREMENTAL;
            PRAGMA journal_mode=WAL;
            PRAGMA busy_timeout=10000;
            CREATE TABLE IF NOT EXISTS observations(
                id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, layer TEXT NOT NULL,
                observed REAL NOT NULL, received REAL NOT NULL, lat REAL, lon REAL,
                payload TEXT NOT NULL, bytes INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS observations_entity_time ON observations(entity_id,observed DESC);
            CREATE INDEX IF NOT EXISTS observations_layer_time ON observations(layer,observed DESC);
            CREATE INDEX IF NOT EXISTS observations_position ON observations(lat,lon);
            CREATE INDEX IF NOT EXISTS observations_sort ON observations(observed DESC,entity_id,id);
            CREATE TABLE IF NOT EXISTS geometry_bounds(observation_id TEXT PRIMARY KEY, west REAL, south REAL, east REAL, north REAL);
            CREATE TABLE IF NOT EXISTS latest(entity_id TEXT PRIMARY KEY, observation_id TEXT NOT NULL, observed REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS changes(sequence INTEGER PRIMARY KEY AUTOINCREMENT, observation_id TEXT, entity_id TEXT, operation TEXT DEFAULT 'upsert');
            CREATE TABLE IF NOT EXISTS publication_outbox(entity_id TEXT PRIMARY KEY, sequence INTEGER NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS publication_state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT OR IGNORE INTO publication_state VALUES('overflow','false');
        """)
        columns = {
            row[1] for row in self._con.execute("PRAGMA table_info(publication_outbox)")
        }
        if "first_sequence" not in columns:
            self._con.execute(
                "ALTER TABLE publication_outbox ADD COLUMN first_sequence INTEGER"
            )
            self._con.execute("UPDATE publication_outbox SET first_sequence=sequence")
            self._con.commit()
        if self.quota_bytes >= 32 * 1024**2:
            # Reserve space for the WAL and a worst-case bounded provider batch.
            pages = max(
                1,
                int(self.quota_bytes * 0.65)
                // self._con.execute("PRAGMA page_size").fetchone()[0],
            )
            self._con.execute(f"PRAGMA max_page_count={pages}")
        self._data_version = self._con.execute("PRAGMA data_version").fetchone()[0]
        self._closed = False

    def ingest(self, observations: list[Observation]) -> list[dict]:
        changed = []
        with self._lock, self._con:
            if observations:
                self._query_cache.clear()
                self._revision += 1
            for observation in observations:
                payload = json.dumps(
                    observation.wire(), separators=(",", ":"), allow_nan=False
                )
                if (
                    self._con.execute(
                        "INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            observation.observation_id,
                            observation.entity_id,
                            observation.layer,
                            observation.observed_at.timestamp(),
                            observation.received_at.timestamp(),
                            observation.position.latitude,
                            observation.position.longitude,
                            payload,
                            len(payload.encode()),
                        ),
                    ).rowcount
                    == 0
                ):
                    continue
                bounds = observation.properties.get("spatial_bounds")
                if bounds:
                    self._con.execute("INSERT OR REPLACE INTO geometry_bounds VALUES(?,?,?,?,?)", (observation.observation_id,bounds["west"],bounds["south"],bounds["east"],bounds["north"]))
                result = self._con.execute(
                    """INSERT INTO latest VALUES(?,?,?)
                    ON CONFLICT(entity_id) DO UPDATE SET observation_id=excluded.observation_id, observed=excluded.observed
                    WHERE excluded.observed >= latest.observed""",
                    (
                        observation.entity_id,
                        observation.observation_id,
                        observation.observed_at.timestamp(),
                    ),
                )
                if result.rowcount:
                    cursor = self._con.execute(
                        "INSERT INTO changes(observation_id,entity_id) VALUES(?,?)",
                        (observation.observation_id, observation.entity_id),
                    )
                    change = {
                        "sequence": cursor.lastrowid,
                        "operation": "upsert",
                        "observation": observation.wire(),
                    }
                    changed.append(change)
                    self._con.execute(
                        "INSERT INTO publication_outbox(entity_id,sequence,payload,first_sequence) VALUES(?,?,?,?) ON CONFLICT(entity_id) DO UPDATE SET sequence=excluded.sequence,payload=excluded.payload",
                        (
                            observation.entity_id,
                            cursor.lastrowid,
                            json.dumps(change, separators=(",", ":")),
                            cursor.lastrowid,
                        ),
                    )
            count = self._con.execute(
                "SELECT COUNT(*) FROM publication_outbox"
            ).fetchone()[0]
            if count > 20000:
                self._con.execute(
                    "DELETE FROM publication_outbox WHERE entity_id IN (SELECT entity_id FROM publication_outbox ORDER BY sequence LIMIT ?)",
                    (count - 20000,),
                )
                self._con.execute(
                    "UPDATE publication_state SET value=CAST(value AS INTEGER)+1 WHERE key='overflow'"
                )
        return changed

    def pending_publications(self, limit=100):
        with self._lock:
            rows = self._con.execute(
                "SELECT payload FROM publication_outbox ORDER BY first_sequence LIMIT ?",
                (max(1, min(limit, 250)),),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def acknowledge_publications(self, changes):
        with self._lock, self._con:
            self._con.executemany(
                "DELETE FROM publication_outbox WHERE entity_id=? AND sequence=?",
                [(c["observation"]["entity_id"], c["sequence"]) for c in changes],
            )

    def publication_status(self):
        with self._lock:
            count = self._con.execute(
                "SELECT COUNT(*) FROM publication_outbox"
            ).fetchone()[0]
            revision = self._con.execute(
                "SELECT value FROM publication_state WHERE key='overflow'"
            ).fetchone()[0]
            overflow = revision not in {"false", "0"}
        return {
            "pending": count,
            "capacity": 20000,
            "coalesced_by_entity": True,
            "resync_required": overflow,
            "resync_revision": revision,
        }

    def acknowledge_publication_resync(self, revision):
        with self._lock, self._con:
            self._con.execute(
                "UPDATE publication_state SET value='false' WHERE key='overflow' AND value=?",
                (revision,),
            )

    def query(
        self,
        *,
        viewport: Viewport | None = None,
        layers=None,
        at: datetime | None = None,
        since: datetime | None = None,
        entity_id=None,
        limit=1000,
        cursor=0,
        snapshot_rowid=None,
    ):
        limit = max(1, min(int(limit), 5000))
        cursor = max(0, int(cursor))
        cache_key = (
            viewport.model_dump_json() if viewport else None,
            tuple(layers or []),
            at.isoformat() if at else None,
            since.isoformat() if since else None,
            entity_id,
            limit,
            cursor,
            snapshot_rowid,
        )
        with self._lock:
            data_version = self._con.execute("PRAGMA data_version").fetchone()[0]
            if data_version != self._data_version:
                self._query_cache.clear()
                self._revision += 1
                self._data_version = data_version
            cached = self._query_cache.get(cache_key)
            if cached is not None:
                self._query_cache.move_to_end(cache_key)
                return json.loads(cached)
        values = []
        clauses = []
        if snapshot_rowid is not None and entity_id is None:
            base = """SELECT o.* FROM observations o WHERE o.rowid IN (
                SELECT rowid FROM (SELECT rowid,ROW_NUMBER() OVER(PARTITION BY entity_id ORDER BY observed DESC,received DESC,rowid DESC) AS rn
                FROM observations WHERE rowid<=? AND observed<=?) WHERE rn=1)"""
            values.extend([snapshot_rowid, at.timestamp() if at else 1e20])
        elif at is None and since is None and entity_id is None:
            base = (
                "SELECT o.* FROM latest l JOIN observations o ON o.id=l.observation_id"
            )
        elif at is not None and entity_id is None:
            base = """SELECT o.* FROM observations o WHERE o.rowid IN (
                SELECT rowid FROM (SELECT rowid,ROW_NUMBER() OVER(PARTITION BY entity_id ORDER BY observed DESC,received DESC) AS rn
                FROM observations WHERE observed<=?) WHERE rn=1)"""
            values.append(at.timestamp())
        else:
            base = "SELECT o.* FROM observations o"
        if entity_id:
            clauses.append("o.entity_id=?")
            values.append(entity_id)
        if at is not None and entity_id:
            clauses.append("o.observed<=?")
            values.append(at.timestamp())
        if since:
            clauses.append("o.observed>=?")
            values.append(since.timestamp())
        if layers:
            clauses.append("o.layer IN (" + ",".join("?" for _ in layers) + ")")
            values.extend(layers)
        if viewport:
            longitude = "(o.lon BETWEEN ? AND ?)" if viewport.west <= viewport.east else "(o.lon>=? OR o.lon<=?)"
            geometry_longitude = "(g.west<=? AND g.east>=?)" if viewport.west <= viewport.east else "(g.west<=? OR g.east>=?)"
            clauses.append(f"((o.lat BETWEEN ? AND ? AND {longitude}) OR EXISTS (SELECT 1 FROM geometry_bounds g WHERE g.observation_id=o.id AND g.south<=? AND g.north>=? AND {geometry_longitude}))")
            values.extend([viewport.south,viewport.north,viewport.west,viewport.east,viewport.north,viewport.south,viewport.east,viewport.west])
        if clauses:
            base += (" AND " if "WHERE o.rowid" in base else " WHERE ") + " AND ".join(
                clauses
            )
        base += " ORDER BY o.observed DESC,o.entity_id,o.id LIMIT ? OFFSET ?"
        values.extend([limit + 1, cursor])
        with self._lock:
            # Sort/index only narrow identity rows; avoid sorting full JSON payloads.
            page = base.replace(
                "SELECT o.* FROM", "SELECT o.id,o.observed,o.entity_id FROM", 1
            )
            rows = self._con.execute(
                "WITH page AS ("
                + page
                + ") SELECT o.payload FROM page p JOIN observations o ON o.id=p.id ORDER BY p.observed DESC,p.entity_id,p.id",
                values,
            ).fetchall()
            sequence = self._con.execute(
                "SELECT COALESCE(MAX(sequence),0) FROM changes"
            ).fetchone()[0]
            snapshot_rowid = (
                snapshot_rowid
                if snapshot_rowid is not None
                else self._con.execute(
                    "SELECT COALESCE(MAX(rowid),0) FROM observations"
                ).fetchone()[0]
            )
            revision = self._revision
        result = {
            "schema_version": "1.0",
            "observations": [json.loads(row["payload"]) for row in rows[:limit]],
            "next_cursor": cursor + limit if len(rows) > limit else None,
            "sequence": sequence,
            "snapshot_rowid": snapshot_rowid,
        }
        encoded = json.dumps(result, separators=(",", ":"))
        with self._lock:
            if revision == self._revision and len(encoded.encode()) <= 8 * 1024**2:
                self._query_cache[cache_key] = encoded
                while (
                    len(self._query_cache) > 8
                    or sum(len(value.encode()) for value in self._query_cache.values())
                    > 16 * 1024**2
                ):
                    self._query_cache.popitem(last=False)
        return result

    def search(self, text, *, at: datetime | None = None, limit=50, scan_limit=200000):
        """Substring match over entity_id and properties.name, newest first.

        Only narrow identity columns are read while matching, so a query that matches
        little does not deserialise every stored payload; full observations are loaded
        for the matched rows alone.
        """
        needle = str(text).strip().lower()
        if not needle:
            return []
        if at is None:
            base = (
                "SELECT o.id,o.entity_id,json_extract(o.payload,'$.properties.name') AS name,"
                "o.observed FROM latest l JOIN observations o ON o.id=l.observation_id"
            )
            values = []
        else:
            base = (
                "SELECT o.id,o.entity_id,json_extract(o.payload,'$.properties.name') AS name,"
                "o.observed FROM observations o WHERE o.rowid IN ("
                "SELECT rowid FROM (SELECT rowid,ROW_NUMBER() OVER("
                "PARTITION BY entity_id ORDER BY observed DESC,received DESC) AS rn "
                "FROM observations WHERE observed<=?) WHERE rn=1)"
            )
            values = [at.timestamp()]
        base += " ORDER BY o.observed DESC,o.entity_id,o.id LIMIT ?"
        values.append(max(1, int(scan_limit)))
        with self._lock:
            identifiers = []
            for row in self._con.execute(base, values):
                name = row["name"]
                if (
                    needle in ("" if name is None else str(name).lower())
                    or needle in row["entity_id"].lower()
                ):
                    identifiers.append(row["id"])
                    if len(identifiers) >= limit:
                        break
            if not identifiers:
                return []
            payloads = dict(
                self._con.execute(
                    "SELECT id,payload FROM observations WHERE id IN ("
                    + ",".join("?" for _ in identifiers)
                    + ")",
                    identifiers,
                ).fetchall()
            )
        # Restore the newest-first order that the IN lookup does not preserve.
        return [
            json.loads(payloads[ident]) for ident in identifiers if ident in payloads
        ]

    def changes(self, after: int, limit=500):
        with self._lock:
            bounds = self._con.execute(
                "SELECT MIN(sequence),MAX(sequence) FROM changes"
            ).fetchone()
            if bounds[0] is not None and (after < bounds[0] - 1 or after > bounds[1]):
                return {"resync": True, "sequence": bounds[1], "changes": []}
            rows = self._con.execute(
                """SELECT c.*,o.payload FROM changes c
                LEFT JOIN observations o ON o.id=c.observation_id WHERE sequence>? ORDER BY sequence LIMIT ?""",
                (max(0, after), max(1, min(limit, 1000))),
            ).fetchall()
        return {
            "resync": False,
            "sequence": rows[-1]["sequence"] if rows else after,
            "changes": [
                {
                    "sequence": row["sequence"],
                    "operation": row["operation"] if row["payload"] else "remove",
                    "entity_id": row["entity_id"],
                    "observation": json.loads(row["payload"])
                    if row["payload"]
                    else None,
                }
                for row in rows
            ],
        }

    def prune(self, now=None):
        cutoff = (time.time() if now is None else now) - self.retention_days * 86400
        with self._lock, self._con:
            self._query_cache.clear()
            self._revision += 1
            self._con.execute("DELETE FROM observations WHERE received<?", (cutoff,))
            size = self._con.execute(
                "SELECT COALESCE(SUM(bytes),0) FROM observations"
            ).fetchone()[0]

            def occupied_bytes():
                pages = self._con.execute("PRAGMA page_count").fetchone()[0]
                free = self._con.execute("PRAGMA freelist_count").fetchone()[0]
                return (pages - free) * self._con.execute(
                    "PRAGMA page_size"
                ).fetchone()[0]

            while size > self.quota_bytes * 0.40 or (
                self.quota_bytes >= 32 * 1024**2
                and occupied_bytes() > self.quota_bytes * 0.55
            ):
                rows = self._con.execute(
                    "SELECT id,bytes FROM observations ORDER BY received LIMIT 1000"
                ).fetchall()
                if not rows:
                    break
                self._con.executemany(
                    "DELETE FROM observations WHERE id=?",
                    [(row["id"],) for row in rows],
                )
                size -= sum(row["bytes"] for row in rows)
            expired = self._con.execute(
                "SELECT entity_id FROM latest WHERE observation_id NOT IN (SELECT id FROM observations)"
            ).fetchall()
            self._con.executemany(
                "INSERT INTO changes(entity_id,operation) VALUES(?,'remove')",
                [(row[0],) for row in expired],
            )
            self._con.execute("DELETE FROM geometry_bounds WHERE observation_id NOT IN (SELECT id FROM observations)")
            self._con.execute(
                "DELETE FROM latest WHERE observation_id NOT IN (SELECT id FROM observations)"
            )
            self._con.execute(
                "DELETE FROM changes WHERE sequence < (SELECT COALESCE(MAX(sequence),0)-20000 FROM changes)"
            )
        with self._lock:
            self._con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._con.execute("PRAGMA incremental_vacuum(4096)")

    def cached_providers(self):
        with self._lock:
            rows = self._con.execute("""SELECT json_extract(o.payload, '$.provenance.provider') AS provider,
                o.layer,COUNT(*) AS count,MAX(o.received) AS received
                FROM latest l JOIN observations o ON o.id=l.observation_id GROUP BY provider,o.layer""").fetchall()
        return [dict(row) for row in rows]

    def stats(self):
        with self._lock:
            row = self._con.execute(
                "SELECT COUNT(*) AS observations,COALESCE(SUM(bytes),0) AS payload_bytes FROM observations"
            ).fetchone()
            entities = self._con.execute("SELECT COUNT(*) FROM latest").fetchone()[0]
        return {
            **dict(row),
            "entities": entities,
            "retention_days": self.retention_days,
            "quota_bytes": self.quota_bytes,
            "database_bytes": sum(
                p.stat().st_size
                for p in (self.path, Path(str(self.path) + "-wal"))
                if p.exists()
            ),
            "delivery": self.publication_status(),
        }

    def close(self):
        with self._lock:
            if not self._closed:
                self._con.close()
                self._closed = True
