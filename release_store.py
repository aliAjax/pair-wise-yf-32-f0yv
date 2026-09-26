"""术前放行记录存储。

只负责 preop_releases 表的结构和读写：每条记录保留提交人、结果和时刻。
判断逻辑见 release_rules.py，展示见 static/release.html。
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS preop_releases(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER NOT NULL REFERENCES allocations(id),
    crossmatch_result TEXT,
    window_start TEXT,
    window_end TEXT,
    decision TEXT NOT NULL,
    missing_json TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT 'hospital',
    submitted_by TEXT NOT NULL,
    submitted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_preop_releases_allocation ON preop_releases(allocation_id, id);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


class ReleaseStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        item = dict(row)
        item["missing"] = json.loads(item.pop("missing_json") or "[]")
        return item

    def record(self, *, allocation_id: int, crossmatch_result: str | None, window_start: str | None, window_end: str | None,
               decision: str, missing: list[dict[str, str]], submitted_by: str, source: str, submitted_at: str) -> dict[str, Any]:
        cur = self.conn.execute(
            """INSERT INTO preop_releases(allocation_id,crossmatch_result,window_start,window_end,decision,missing_json,source,submitted_by,submitted_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (allocation_id, crossmatch_result, window_start, window_end, decision,
             json.dumps(missing, ensure_ascii=False), source, submitted_by, submitted_at))
        return self._decode(self.conn.execute("SELECT * FROM preop_releases WHERE id=?", (cur.lastrowid,)).fetchone())

    def latest(self, allocation_id: int) -> dict[str, Any] | None:
        return self._decode(self.conn.execute(
            "SELECT * FROM preop_releases WHERE allocation_id=? ORDER BY id DESC LIMIT 1", (allocation_id,)).fetchone())

    def history(self, allocation_id: int) -> list[dict[str, Any]]:
        return [self._decode(r) for r in self.conn.execute(
            "SELECT * FROM preop_releases WHERE allocation_id=? ORDER BY id", (allocation_id,))]
