import os
import ast
import json
import re
import logging
import traceback
from typing import Optional, Dict, Any, List, Tuple
from pydantic import BaseModel, Field
from openai import OpenAI

from config import settings
from memory_manager import MemoryManager
from planner_agent import TaskStep, ProjectPlan

logger = logging.getLogger(__name__)


class ExecutionResult(BaseModel):
    """Stores the execution result of a code generation step or file creation."""

    success: bool
    file_path: str
    code: str = ""
    error_message: Optional[str] = None
    iterations: int = 1
    logs: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CodeGeneratorAgent:
    """Agent responsible for writing, validating, and self-correcting project code files."""

    def __init__(self, memory_manager: Optional[MemoryManager] = None) -> None:
        self.memory_manager = memory_manager or MemoryManager()
        api_key = (
            getattr(settings, "openai_api_key", None)
            or getattr(settings, "llm_api_key", None)
            or os.getenv("OPENAI_API_KEY", "fallback_key")
        )
        base_url = getattr(settings, "llm_base_url", None) or getattr(
            settings, "openai_base_url", None
        )
        model_name = getattr(settings, "llm_model", None) or "gpt-4o-mini"

        client_kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        self.client = OpenAI(**client_kwargs)
        self.model = model_name

    def _clean_code_output(self, raw_code: str) -> str:
        """Strips markdown code blocks and formatting artifacts from LLM response."""
        code = raw_code.strip()
        pattern = r"^```(?:\w+)?\n([\s\S]*?)\n```$"
        match = re.match(pattern, code)
        if match:
            return match.group(1).strip()

        # Fallback inline removal
        if code.startswith("```"):
            lines = code.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            return "\n".join(lines).strip()

        return code

    def validate_code_syntax(self, file_path: str, code: str) -> Tuple[bool, str]:
        """Validates code syntax based on file extension."""
        if not code or not code.strip():
            return False, "Generated code is empty."

        ext = os.path.splitext(file_path)[1].lower()

        if ext == ".py":
            try:
                ast.parse(code)
                return True, "Python syntax check passed."
            except SyntaxError as syntax_err:
                error_msg = f"Python Syntax Error on line {syntax_err.lineno}: {syntax_err.msg}"
                return False, error_msg
            except Exception as parse_err:
                return False, f"Python parsing error: {str(parse_err)}"

        elif ext == ".json":
            try:
                json.loads(code)
                return True, "JSON syntax check passed."
            except json.JSONDecodeError as json_err:
                return (
                    False,
                    f"JSON Error line {json_err.lineno} col {json_err.colno}: {json_err.msg}",
                )

        return True, f"No syntax check required for {ext} file."

    def write_file(self, project_dir: str, file_path: str, code: str) -> str:
        """Writes generated code safely to local disk."""
        clean_relative_path = file_path.lstrip("/\\")
        full_path = os.path.normpath(os.path.join(project_dir, clean_relative_path))

        # Security check: Ensure target path remains within project_dir
        if not full_path.startswith(os.path.abspath(project_dir)):
            raise ValueError(f"Target path {file_path} escapes project directory root.")

        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(code)

        logger.info(f"Successfully written code to file: {full_path}")
        return full_path

    def generate_code(
        self,
        project_id: str,
        task: TaskStep,
        plan: Optional[ProjectPlan] = None,
        memory_context: str = "",
    ) -> str:
        """Generates source code for a specific step using LLM."""
        plan_summary = ""
        if plan:
            plan_summary = (
                f"Project Title: {plan.title}\n"
                f"Architecture: {plan.architecture_overview}\n"
                f"Tech Stack: {', '.join(plan.tech_stack)}\n"
            )

        system_prompt = (
            "You are an expert software developer and system architect. "
            "Write complete, production-ready, clean, well-documented source code. "
            "Never use placeholders, '...', or missing imports. "
            "Return ONLY the code without markdown explanation blocks if possible."
        )

        user_prompt = (
            f"--- PROJECT CONTEXT ---\n{plan_summary}\n"
            f"--- TASK DETAILS ---\n"
            f"Step ID: {task.step_id}\n"
            f"Title: {task.title}\n"
            f"Description: {task.description}\n"
            f"Target File Path: {task.file_path}\n\n"
            f"--- PREVIOUS MEMORY & KNOWN ERRORS ---\n{memory_context}\n\n"
            f"Please generate the complete source code for file '{task.file_path}'."
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            )
            raw_content = response.choices[0].message.content or ""
            return self._clean_code_output(raw_content)
        except Exception as e:
            logger.error(f"LLM code generation failed for {task.file_path}: {e}")
            raise RuntimeError(f"Code generation failed: {str(e)}")

    def fix_code(
        self,
        project_id: str,
        file_path: str,
        broken_code: str,
        error_message: str,
        task: Optional[TaskStep] = None,
        memory_context: str = "",
    ) -> str:
        """Applies self-correction by requesting code fix from LLM based on error logs."""
        system_prompt = (
            "You are an automated self-correcting code debugging agent. "
            "Analyze the provided code and syntax/runtime error log. "
            "Fix the bug completely. Return ONLY the fully corrected, production-ready source code."
        )

        task_info = f"Task: {task.title}\nDescription: {task.description}" if task else ""

        user_prompt = (
            f"Target File Path: {file_path}\n"
            f"{task_info}\n\n"
            f"--- BROKEN SOURCE CODE ---\n{broken_code}\n\n"
            f"--- ENCOUNTERED ERROR ---\n{error_message}\n\n"
            f"--- MEMORY / LESSONS LEARNED ---\n{memory_context}\n\n"
            f"Identify the exact cause of the failure and output the complete fixed code."
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
            )
            raw_content = response.choices[0].message.content or ""
            return self._clean_code_output(raw_content)
        except Exception as e:
            logger.error(f"LLM code self-correction failed for {file_path}: {e}")
            return broken_code

    def execute_task(
        self,
        project_id: str,
        task: TaskStep,
        project_dir: str,
        plan: Optional[ProjectPlan] = None,
        max_retries: int = 3,
    ) -> ExecutionResult:
        """Executes a code generation task step with self-correction retry loop."""
        logs: List[str] = []
        file_path = task.file_path or f"step_{task.step_id}.py"

        logs.append(f"Starting execution for task {task.step_id}: {task.title}")
        self.memory_manager.record_step(
            project_id=project_id,
            step_name=f"Execute Task {task.step_id}",
            status="in_progress",
            details={"file_path": file_path, "title": task.title},
        )

        memory_context = self.memory_manager.format_memory_for_prompt(project_id)

        current_code = ""
        iteration = 0

        while iteration < max_retries:
            iteration += 1
            logs.append(f"Iteration {iteration}/{max_retries}: Generating code...")

            try:
                if iteration == 1:
                    current_code = self.generate_code(
                        project_id=project_id,
                        task=task,
                        plan=plan,
                        memory_context=memory_context,
                    )
                else:
                    last_error = logs[-1] if logs else "Validation failure"
                    current_code = self.fix_code(
                        project_id=project_id,
                        file_path=file_path,
                        broken_code=current_code,
                        error_message=last_error,
                        task=task,
                        memory_context=memory_context,
                    )

                is_valid, validation_msg = self.validate_code_syntax(
                    file_path=file_path, code=current_code
                )

                if is_valid:
                    full_disk_path = self.write_file(
                        project_dir=project_dir, file_path=file_path, code=current_code
                    )
                    logs.append(f"Syntax validation passed: {validation_msg}")
                    logs.append(f"Saved file to {full_disk_path}")

                    self.memory_manager.record_step(
                        project_id=project_id,
                        step_name=f"Execute Task {task.step_id}",
                        status="completed",
                        details={
                            "file_path": file_path,
                            "iterations": iteration,
                            "full_path": full_disk_path,
                        },
                    )

                    return ExecutionResult(
                        success=True,
                        file_path=file_path,
                        code=current_code,
                        iterations=iteration,
                        logs=logs,
                        metadata={"full_disk_path": full_disk_path},
                    )
                else:
                    error_msg = f"Validation failed on iteration {iteration}: {validation_msg}"
                    logs.append(error_msg)
                    logger.warning(
                        f"Project {project_id} | File {file_path} | {error_msg}"
                    )

                    self.memory_manager.record_error(
                        project_id=project_id,
                        error_type="SyntaxValidationError",
                        error_message=validation_msg,
                        code_context=current_code[:500],
                        task_id=str(task.step_id),
                    )

            except Exception as exc:
                exc_msg = f"Error during task iteration {iteration}: {str(exc)}"
                logs.append(exc_msg)
                logger.error(f"{exc_msg}\n{traceback.format_exc()}")

                self.memory_manager.record_error(
                    project_id=project_id,
                    error_type="ExecutionException",
                    error_message=str(exc),
                    code_context=current_code[:500] if current_code else "",
                    task_id=str(task.step_id),
                )

        # Max retries exceeded
        failure_msg = (
            f"Failed to produce valid code for '{file_path}' after {max_retries} retries."
        )
        logs.append(failure_msg)

        # Attempt best-effort file saving
        if current_code:
            try:
                self.write_file(
                    project_dir=project_dir, file_path=file_path, code=current_code
                )
                logs.append("Saved unverified fallback code to disk.")
            except Exception as write_err:
                logs.append(f"Failed to write fallback code: {write_err}")

        self.memory_manager.record_step(
            project_id=project_id,
            step_name=f"Execute Task {task.step_id}",
            status="failed",
            details={"file_path": file_path, "logs": logs},
        )

        return ExecutionResult(
            success=False,
            file_path=file_path,
            code=current_code,
            error_message=failure_msg,
            iterations=iteration,
            logs=logs,
        )

    def generate_project_files(
        self,
        project_id: str,
        plan: ProjectPlan,
        project_dir: str,
        max_retries: int = 3,
    ) -> List[ExecutionResult]:
        """Generates all files specified in the project plan sequentially."""
        results: List[ExecutionResult] = []
        os.makedirs(project_dir, exist_ok=True)

        logger.info(
            f"Generating {len(plan.steps)} project steps/files for project '{project_id}' in {project_dir}"
        )

        for task in plan.steps:
            res = self.execute_task(
                project_id=project_id,
                task=task,
                project_dir=project_dir,
                plan=plan,
                max_retries=max_retries,
            )
            results.append(res)

        return results
