"""术前放行记录的持久化。

只负责放行记录的存取，一条提交对应一条记录，未通过的提交同样保留；
判断规则在 clearance.py，页面在 static/clearance.html，互不耦合。
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS clearance_records(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER NOT NULL REFERENCES allocations(id),
    submitted_by TEXT NOT NULL,
    submitter_role TEXT NOT NULL,
    crossmatch_compatible INTEGER,
    surgeon_available_at TEXT,
    decision TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    backfilled INTEGER NOT NULL DEFAULT 0,
    submitted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clearance_allocation ON clearance_records(allocation_id, id);
"""


class ClearanceStore:
    def __init__(self, conn: sqlite3.Connection):
        conn.executescript(SCHEMA)

    @staticmethod
    def add(
        conn: sqlite3.Connection,
        allocation_id: int,
        submitted_by: str,
        submitter_role: str,
        crossmatch_compatible: bool | None,
        surgeon_available_at: str | None,
        evaluation: dict[str, Any],
        backfilled: bool,
        submitted_at: str,
        review_deadline: str,
    ) -> int:
        detail = {
            "review_deadline": review_deadline,
            "remaining_minutes": evaluation["remaining_minutes"],
            "limits": evaluation["limits"],
        }
        cur = conn.execute(
            """INSERT INTO clearance_records(allocation_id,submitted_by,submitter_role,crossmatch_compatible,
                  surgeon_available_at,decision,reasons_json,detail_json,backfilled,submitted_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (allocation_id, submitted_by, submitter_role,
             None if crossmatch_compatible is None else int(crossmatch_compatible),
             surgeon_available_at, evaluation["decision"],
             json.dumps(evaluation["reasons"], ensure_ascii=False),
             json.dumps(detail, ensure_ascii=False, sort_keys=True),
             int(backfilled), submitted_at),
        )
        return int(cur.lastrowid)

    @staticmethod
    def latest_for(conn: sqlite3.Connection, allocation_id: int) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM clearance_records WHERE allocation_id=? ORDER BY id DESC LIMIT 1", (allocation_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_for(conn: sqlite3.Connection, allocation_id: int) -> list[dict[str, Any]]:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM clearance_records WHERE allocation_id=? ORDER BY id", (allocation_id,))]

    @staticmethod
    def latest_map(conn: sqlite3.Connection) -> dict[int, dict[str, Any]]:
        """各分配最新一条放行记录，供列表视图批量使用。"""
        rows = conn.execute("""SELECT cr.* FROM clearance_records cr
                               JOIN (SELECT allocation_id, MAX(id) max_id FROM clearance_records GROUP BY allocation_id) m
                                 ON m.max_id = cr.id""")
        return {int(r["allocation_id"]): dict(r) for r in rows}

    @staticmethod
    def render(record: dict[str, Any]) -> dict[str, Any]:
        """把存储行整理成对外 JSON 结构。"""
        return {
            "id": record["id"],
            "allocation_id": record["allocation_id"],
            "submitted_by": record["submitted_by"],
            "submitter_role": record["submitter_role"],
            "crossmatch_compatible": None if record["crossmatch_compatible"] is None
            else bool(record["crossmatch_compatible"]),
            "surgeon_available_at": record["surgeon_available_at"],
            "decision": record["decision"],
            "reasons": json.loads(record["reasons_json"]),
            "detail": json.loads(record["detail_json"]),
            "backfilled": bool(record["backfilled"]),
            "submitted_at": record["submitted_at"],
        }
