import json
import logging
from typing import Any, Dict, List, Optional

from db import (
    get_db_connection,
    get_project_memory,
    log_execution_step,
    save_error_log,
    save_project_memory,
    update_error_resolution,
)

logger = logging.getLogger(__name__)


class MemoryManager:
    """Manages project memory, execution history, error logs, and context injection for agents."""

    def __init__(self) -> None:
        pass

    async def record_error(
        self,
        project_id: str,
        error_type: str,
        error_message: str,
        code_context: str = "",
        resolution: str = "",
        task_id: str = "",
    ) -> int:
        """Records an error encountered during project generation or execution."""
        try:
            error_id = await save_error_log(
                project_id=project_id,
                error_type=error_type,
                error_message=error_message,
                code_context=code_context,
                resolution=resolution,
                task_id=task_id,
            )
            logger.info("Recorded error ID %s for project %s", error_id, project_id)
            return error_id
        except Exception as e:
            logger.error("Failed to record error for project %s: %s", project_id, e)
            return -1

    async def resolve_error(self, error_id: int, resolution: str) -> bool:
        """Updates the resolution of a previously recorded error."""
        try:
            success = await update_error_resolution(error_id=error_id, resolution=resolution)
            if success:
                logger.info("Successfully updated resolution for error ID %s", error_id)
            return success
        except Exception as e:
            logger.error("Failed to update resolution for error ID %s: %s", error_id, e)
            return False

    async def save_context(
        self,
        project_id: str,
        idea: str,
        status: str = "active",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Saves or updates project state and contextual metadata."""
        try:
            await save_project_memory(
                project_id=project_id, idea=idea, status=status, context=context
            )
            logger.info("Saved memory context for project %s", project_id)
        except Exception as e:
            logger.error("Failed to save memory context for project %s: %s", project_id, e)

    async def get_context(self, project_id: str) -> Dict[str, Any]:
        """Retrieves saved project memory and metadata."""
        try:
            return await get_project_memory(project_id)
        except Exception as e:
            logger.error("Failed to retrieve context for project %s: %s", project_id, e)
            return {}

    async def record_step(
        self,
        project_id: str,
        step_name: str,
        status: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Logs an execution step for a project."""
        try:
            return await log_execution_step(
                project_id=project_id, step_name=step_name, status=status, details=details
            )
        except Exception as e:
            logger.error("Failed to log step %s for project %s: %s", step_name, project_id, e)
            return -1

    async def get_project_errors(self, project_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieves recent error logs for a specific project."""
        try:
            async with get_db_connection() as db:
                cursor = await db.execute(
                    """
                    SELECT id, project_id, task_id, error_type, error_message, code_context, resolution, created_at
                    FROM error_logs
                    WHERE project_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (project_id, limit),
                )
                rows = await cursor.fetchall()
                results = []
                for row in rows:
                    results.append({
                        "id": row[0],
                        "project_id": row[1],
                        "task_id": row[2],
                        "error_type": row[3],
                        "error_message": row[4],
                        "code_context": row[5],
                        "resolution": row[6],
                        "created_at": row[7],
                    })
                return results
        except Exception as e:
            logger.error("Error fetching errors for project %s: %s", project_id, e)
            return []

    async def get_all_resolved_errors(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Retrieves global resolved errors across projects to prevent repeating known mistakes."""
        try:
            async with get_db_connection() as db:
                cursor = await db.execute(
                    """
                    SELECT id, project_id, task_id, error_type, error_message, code_context, resolution, created_at
                    FROM error_logs
                    WHERE resolution IS NOT NULL AND resolution != ''
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
                rows = await cursor.fetchall()
                results = []
                for row in rows:
                    results.append({
                        "id": row[0],
                        "project_id": row[1],
                        "task_id": row[2],
                        "error_type": row[3],
                        "error_message": row[4],
                        "code_context": row[5],
                        "resolution": row[6],
                        "created_at": row[7],
                    })
                return results
        except Exception as e:
            logger.error("Error fetching resolved errors: %s", e)
            return []

    async def get_execution_history(self, project_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Retrieves execution step logs for a project."""
        try:
            async with get_db_connection() as db:
                cursor = await db.execute(
                    """
                    SELECT id, project_id, step_name, status, details, created_at
                    FROM execution_logs
                    WHERE project_id = ?
                    ORDER BY id ASC
                    LIMIT ?
                    """,
                    (project_id, limit),
                )
                rows = await cursor.fetchall()
                results = []
                for row in rows:
                    raw_details = row[4]
                    details = {}
                    if raw_details:
                        try:
                            details = json.loads(raw_details)
                        except json.JSONDecodeError:
                            details = {"raw": raw_details}
                    results.append({
                        "id": row[0],
                        "project_id": row[1],
                        "step_name": row[2],
                        "status": row[3],
                        "details": details,
                        "created_at": row[5],
                    })
                return results
        except Exception as e:
            logger.error("Error fetching execution logs for project %s: %s", project_id, e)
            return []

    async def format_memory_for_prompt(self, project_id: str) -> str:
        """Formats errors, past resolutions, and project history into a structured prompt chunk

        for AI agents to consume and avoid past mistakes.
        """
        project_errors = await self.get_project_errors(project_id=project_id, limit=5)
        resolved_errors = await self.get_all_resolved_errors(limit=5)

        if not project_errors and not resolved_errors:
            return "No prior error history or special guidelines recorded for this project context."

        memory_sections = []

        if project_errors:
            memory_sections.append("=== RECENT PROJECT ERRORS & ISSUES ===")
            for idx, err in enumerate(project_errors, 1):
                section = f"{idx}. [Type: {err['error_type']}] {err['error_message']}"
                if err.get("code_context"):
                    section += f"\n   Context: {err['code_context'][:200]}"
                if err.get("resolution"):
                    section += f"\n   Resolution/Fix applied: {err['resolution']}"
                memory_sections.append(section)

        if resolved_errors:
            memory_sections.append("\n=== GLOBAL LESSONS LEARNED & PREVIOUS FIXES ===")
            for idx, err in enumerate(resolved_errors, 1):
                section = f"{idx}. Error: {err['error_message']}\n   Solution: {err['resolution']}"
                memory_sections.append(section)

        return "\n".join(memory_sections)
