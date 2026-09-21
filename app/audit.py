import asyncio
import os
import sqlite3
import sys
import time
from typing import List, Dict, Any, Optional
from app.models import DecisionRecord, RunSummary


class AuditSink:
    """
    Asynchronous write-only SQLite audit sink.
    All control loop decisions are queued in memory and written in the background.
    Any database I/O error or deadlock is caught, logged, and isolated from the live control loop.
    """

    def __init__(self, db_path: str = "data/audit.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self.queue: asyncio.Queue[DecisionRecord] = asyncio.Queue(maxsize=10000)
        self.worker_task: Optional[asyncio.Task] = None
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS decisions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL,
                        ts REAL NOT NULL,
                        iso_time TEXT NOT NULL,
                        primary_ppm REAL NOT NULL,
                        verification_ppm REAL NOT NULL,
                        flow REAL NOT NULL,
                        requested_dose REAL NOT NULL,
                        actual_dose REAL NOT NULL,
                        resulting_ppm REAL NOT NULL,
                        ph REAL NOT NULL,
                        interlock_on INTEGER NOT NULL,
                        decision TEXT NOT NULL,
                        reason TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_decisions_run_id ON decisions(run_id)")
                conn.commit()
        except Exception as e:
            print(f"[AUDIT SINK INIT ERROR] Failed to initialize SQLite database: {e}", file=sys.stderr)

    async def start(self) -> None:
        if self.worker_task is None or self.worker_task.done():
            self.worker_task = asyncio.create_task(self._writer_loop())

    async def stop(self) -> None:
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass

    def enqueue(self, record: DecisionRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except asyncio.QueueFull:
            print("[AUDIT SINK WARN] Queue full, dropping audit record to protect control loop", file=sys.stderr)

    async def _writer_loop(self) -> None:
        while True:
            try:
                record = await self.queue.get()
                self._write_record(record)
                self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[AUDIT SINK ERROR] Unexpected error in audit writer loop: {e}", file=sys.stderr)
                await asyncio.sleep(0.5)

    def _write_record(self, record: DecisionRecord) -> None:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO decisions (
                        run_id, ts, iso_time, primary_ppm, verification_ppm, flow,
                        requested_dose, actual_dose, resulting_ppm, ph,
                        interlock_on, decision, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record.run_id,
                    record.ts,
                    record.iso_time,
                    record.primary_ppm,
                    record.verification_ppm,
                    record.flow,
                    record.requested_dose,
                    record.actual_dose,
                    record.resulting_ppm,
                    record.ph,
                    1 if record.interlock_on else 0,
                    record.decision.value if hasattr(record.decision, 'value') else str(record.decision),
                    record.reason
                ))
                conn.commit()
        except Exception as e:
            print(f"[AUDIT SINK WRITE ERROR] Could not persist decision to SQLite: {e}", file=sys.stderr)

    def get_runs(self) -> List[RunSummary]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT 
                        run_id, 
                        MIN(iso_time) as start_time,
                        COUNT(*) as total_decisions,
                        SUM(CASE WHEN decision = 'BLOCKED' THEN 1 ELSE 0 END) as blocked_decisions
                    FROM decisions
                    GROUP BY run_id
                    ORDER BY MIN(ts) DESC
                """)
                rows = cursor.fetchall()
                return [
                    RunSummary(
                        run_id=row["run_id"],
                        start_time=row["start_time"] or "unknown",
                        total_decisions=row["total_decisions"],
                        blocked_decisions=row["blocked_decisions"] or 0
                    )
                    for row in rows
                ]
        except Exception as e:
            print(f"[AUDIT SINK READ ERROR] Failed to query runs: {e}", file=sys.stderr)
            return []

    def get_run_decisions(self, run_id: str, limit: int = 500) -> List[Dict[str, Any]]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM decisions 
                    WHERE run_id = ? 
                    ORDER BY ts ASC 
                    LIMIT ?
                """, (run_id, limit))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"[AUDIT SINK READ ERROR] Failed to query decisions for run {run_id}: {e}", file=sys.stderr)
            return []
