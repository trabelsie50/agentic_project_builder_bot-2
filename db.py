import json
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import aiosqlite

from config import settings


def get_db_path() -> str:
    """Retrieves the SQLite database path from system settings or defaults to local data storage."""
    if hasattr(settings, "db_path") and settings.db_path:
        return str(settings.db_path)
    if hasattr(settings, "database_url") and settings.database_url:
        db_url = str(settings.database_url)
        if db_url.startswith("sqlite:///"):
            return db_url.replace("sqlite:///", "")
        return db_url
    return "data/agentic_memory.db"


@asynccontextmanager
async def get_db_connection():
    """Async context manager for managing SQLite database connections."""
    db_path = get_db_path()
    db_dir = os.path.dirname(os.path.abspath(db_path))
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        yield conn


async def init_db() -> None:
    """Initializes the SQLite database schema and creates necessary tables for memory and execution logs."""
    async with get_db_connection() as conn:
        await conn.execute("PRAGMA foreign_keys = ON;")

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                idea TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'initialized',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                context_json TEXT DEFAULT '{}'
            );
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS error_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                task_id TEXT DEFAULT '',
                error_type TEXT NOT NULL,
                error_message TEXT NOT NULL,
                code_context TEXT DEFAULT '',
                resolution TEXT DEFAULT '',
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
            );
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS execution_context (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                step_name TEXT NOT NULL,
                status TEXT NOT NULL,
                details_json TEXT DEFAULT '{}',
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
            );
            """
        )

        await conn.commit()


async def save_error_log(
    project_id: str,
    error_type: str,
    error_message: str,
    code_context: str = "",
    resolution: str = "",
    task_id: str = "",
) -> int:
    """Saves an error log entry into the database for future agent learning and context injection."""
    async with get_db_connection() as conn:
        await conn.execute(
            """
            INSERT OR IGNORE INTO projects (project_id, idea, status)
            VALUES (?, ?, ?)
            """,
            (project_id, "Auto-registered project context", "active"),
        )

        cursor = await conn.execute(
            """
            INSERT INTO error_logs (project_id, task_id, error_type, error_message, code_context, resolution)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (project_id, task_id, error_type, error_message, code_context, resolution),
        )

        await conn.execute(
            """
            UPDATE projects 
            SET updated_at = CURRENT_TIMESTAMP 
            WHERE project_id = ?
            """,
            (project_id,),
        )

        await conn.commit()
        return cursor.lastrowid or 0


async def save_project_memory(project_id: str, idea: str, status: str = "active", context: Optional[Dict[str, Any]] = None) -> None:
    """Creates or updates a project memory entry with contextual metadata."""
    context_data = json.dumps(context or {})
    async with get_db_connection() as conn:
        await conn.execute(
            """
            INSERT INTO projects (project_id, idea, status, context_json, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(project_id) DO UPDATE SET
                idea = EXCLUDED.idea,
                status = EXCLUDED.status,
                context_json = EXCLUDED.context_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (project_id, idea, status, context_data),
        )
        await conn.commit()


async def log_execution_step(project_id: str, step_name: str, status: str, details: Optional[Dict[str, Any]] = None) -> int:
    """Logs an execution step details into the execution history table."""
    details_str = json.dumps(details or {})
    async with get_db_connection() as conn:
        await conn.execute(
            """
            INSERT OR IGNORE INTO projects (project_id, idea, status)
            VALUES (?, ?, ?)
            """,
            (project_id, "Auto-registered execution step", "active"),
        )

        cursor = await conn.execute(
            """
            INSERT INTO execution_context (project_id, step_name, status, details_json)
            VALUES (?, ?, ?, ?)
            """,
            (project_id, step_name, status, details_str),
        )
        await conn.commit()
        return cursor.lastrowid or 0


async def update_error_resolution(error_id: int, resolution: str) -> bool:
    """Updates the resolution field for a logged error once solved."""
    async with get_db_connection() as conn:
        cursor = await conn.execute(
            """
            UPDATE error_logs
            SET resolution = ?
            WHERE id = ?
            """,
            (resolution, error_id),
        )
        await conn.commit()
        return cursor.rowcount > 0


async def get_project_memory(project_id: str) -> Dict[str, Any]:
    """Retrieves full memory footprint of a project including execution history, context, and error logs."""
    async with get_db_connection() as conn:
        project_cursor = await conn.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,))
        project_row = await project_cursor.fetchone()

        if not project_row:
            return {
                "project_id": project_id,
                "exists": False,
                "idea": "",
                "status": "not_found",
                "errors": [],
                "execution_history": [],
                "context": {},
            }

        error_cursor = await conn.execute(
            """
            SELECT id, task_id, error_type, error_message, code_context, resolution, timestamp 
            FROM error_logs 
            WHERE project_id = ? 
            ORDER BY timestamp ASC
            """,
            (project_id,),
        )
        error_rows = await error_cursor.fetchall()
        errors: List[Dict[str, Any]] = [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "error_type": row["error_type"],
                "error_message": row["error_message"],
                "code_context": row["code_context"],
                "resolution": row["resolution"],
                "timestamp": str(row["timestamp"]),
            }
            for row in error_rows
        ]

        exec_cursor = await conn.execute(
            """
            SELECT id, step_name, status, details_json, timestamp 
            FROM execution_context 
            WHERE project_id = ? 
            ORDER BY timestamp ASC
            """,
            (project_id,),
        )
        exec_rows = await exec_cursor.fetchall()
        execution_history: List[Dict[str, Any]] = []
        for row in exec_rows:
            details = {}
            if row["details_json"]:
                try:
                    details = json.loads(row["details_json"])
                except json.JSONDecodeError:
                    details = {"raw": row["details_json"]}
            execution_history.append(
                {
                    "id": row["id"],
                    "step_name": row["step_name"],
                    "status": row["status"],
                    "details": details,
                    "timestamp": str(row["timestamp"]),
                }
            )

        context_data = {}
        if project_row["context_json"]:
            try:
                context_data = json.loads(project_row["context_json"])
            except json.JSONDecodeError:
                context_data = {}

        return {
            "project_id": project_id,
            "exists": True,
            "idea": project_row["idea"],
            "status": project_row["status"],
            "created_at": str(project_row["created_at"]),
            "updated_at": str(project_row["updated_at"]),
            "context": context_data,
            "errors": errors,
            "execution_history": execution_history,
        }
