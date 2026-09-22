from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from .models import PhotoRecord


class EventDatabase:
    def __init__(self, path: Path, readonly: bool = False):
        self.path = path
        self.readonly = readonly
        if readonly:
            if not path.is_file():
                raise FileNotFoundError(path)
            self.connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        if not readonly:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS photos (
                    path TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def get(self, path: Path, fingerprint: str | None = None) -> PhotoRecord | None:
        row = self.connection.execute("SELECT fingerprint, payload FROM photos WHERE path=?", (str(path),)).fetchone()
        if row is None or (fingerprint is not None and row["fingerprint"] != fingerprint):
            return None
        return PhotoRecord.from_dict(json.loads(row["payload"]))

    def put(self, record: PhotoRecord) -> None:
        self.connection.execute(
            "INSERT INTO photos(path, fingerprint, payload) VALUES(?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET fingerprint=excluded.fingerprint, "
            "payload=excluded.payload, updated_at=CURRENT_TIMESTAMP",
            (record.path, record.content_fingerprint, json.dumps(record.to_dict(), sort_keys=True)),
        )
        self.connection.commit()

    def all(self) -> list[PhotoRecord]:
        rows = self.connection.execute("SELECT payload FROM photos ORDER BY path").fetchall()
        return [PhotoRecord.from_dict(json.loads(row["payload"])) for row in rows]

    def set_manual_decision(self, path: str, decision: str | None) -> None:
        record = self.get(Path(path))
        if record is None:
            raise KeyError(path)
        record.manual_decision = decision
        self.put(record)

    def replace_all(self, records: Iterable[PhotoRecord]) -> None:
        for record in records:
            self.put(record)

    def remove_missing(self, active_paths: set[str]) -> None:
        rows = self.connection.execute("SELECT path FROM photos").fetchall()
        stale = [(row["path"],) for row in rows if row["path"] not in active_paths]
        if stale:
            self.connection.executemany("DELETE FROM photos WHERE path=?", stale)
            self.connection.commit()
