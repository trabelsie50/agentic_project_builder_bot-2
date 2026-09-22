import json
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ValidationError
from openai import AsyncOpenAI

from config import settings
from memory_manager import MemoryManager

logger = logging.getLogger(__name__)


class TaskStep(BaseModel):
    task_id: str = Field(description="Unique ID for the task step, e.g., task_1")
    title: str = Field(description="Short summary of what this step accomplishes")
    description: str = Field(description="Detailed instructions and implementation requirements")
    file_path: Optional[str] = Field(default=None, description="Path to the primary file targeted by this task")
    action: str = Field(default="create_file", description="Action type: create_file, update_file, configure, test")
    dependencies: List[str] = Field(default_factory=list, description="Task IDs that must complete before this step")


class ProjectPlan(BaseModel):
    project_id: str = Field(description="Unique identifier for the project")
    idea: str = Field(description="Original user idea/concept")
    summary: str = Field(description="High-level technical overview of the proposed solution")
    architecture: str = Field(description="Architectural breakdown and design choices")
    file_structure: List[str] = Field(default_factory=list, description="List of all relative file paths to create")
    tasks: List[TaskStep] = Field(default_factory=list, description="Ordered sequence of execution tasks")
    environment_variables: Dict[str, str] = Field(default_factory=dict, description="Required environment variables")
    dependencies: List[str] = Field(default_factory=list, description="External library dependencies")


class PlannerAgent:
    """
    Planner Agent responsible for analyzing user ideas, converting them into structured project plans,
    decomposing requirements into sequential steps, and integrating execution memory to avoid past errors.
    """

    def __init__(self, memory_manager: Optional[MemoryManager] = None):
        self.memory_manager = memory_manager
        api_key = getattr(settings, "openai_api_key", None) or getattr(settings, "OPENAI_API_KEY", "")
        self.client = AsyncOpenAI(api_key=api_key) if api_key else AsyncOpenAI()
        self.model = getattr(settings, "openai_model", None) or getattr(settings, "llm_model", "gpt-4o")

    def _get_system_prompt(self) -> str:
        return (
            "You are an expert Lead Software Architect and Technical Project Planner.\n"
            "Your role is to transform raw software project ideas into precise, fully executable technical project plans.\n"
            "You must generate output strictly in standard JSON format matching the expected schema.\n\n"
            "Guidelines:\n"
            "1. Focus on robust, production-ready software designs (defaulting to Python, FastAPI, SQLite, JWT, Docker, and GitHub workflows when appropriate).\n"
            "2. Break down the project into logical, step-by-step tasks. Ensure tasks are strictly ordered with proper dependencies.\n"
            "3. Specify every required file in the 'file_structure' array.\n"
            "4. Take note of any historical error context provided and design the steps to avoid past mistakes.\n"
            "5. Make sure the response is raw JSON with no Markdown wrappers outside the JSON object."
        )

    def _build_prompt(self, idea: str, memory_context: str) -> str:
        prompt = f"User Project Idea:\n{idea}\n\n"
        if memory_context:
            prompt += f"Project Memory & Lessons Learned from Past Executions:\n{memory_context}\n\n"
        
        prompt += (
            "Decompose this idea into a structured implementation plan. Return a JSON object with this structure:\n"
            "{\n"
            '  "project_id": "string",\n'
            '  "idea": "string",\n'
            '  "summary": "string",\n'
            '  "architecture": "string",\n'
            '  "file_structure": ["path/file1.py", "requirements.txt", "Dockerfile"],\n'
            '  "tasks": [\n'
            "    {\n"
            '      "task_id": "task_1",\n'
            '      "title": "string",\n'
            '      "description": "detailed technical requirements",\n'
            '      "file_path": "path/file1.py",\n'
            '      "action": "create_file",\n'
            '      "dependencies": []\n'
            "    }\n"
            "  ],\n"
            '  "environment_variables": {"KEY": "DEFAULT_VALUE"},\n'
            '  "dependencies": ["fastapi", "uvicorn", "pydantic"]\n'
            "}\n"
        )
        return prompt

    async def plan_project(self, idea: str, project_id: str) -> ProjectPlan:
        """
        Analyzes the idea, consults past memory context, and builds a comprehensive ProjectPlan.
        """
        logger.info(f"Starting planning phase for project '{project_id}'...")
        
        memory_context = ""
        if self.memory_manager:
            try:
                memory_context = self.memory_manager.format_memory_for_prompt(project_id)
            except Exception as e:
                logger.warning(f"Could not retrieve memory context for {project_id}: {e}")

        system_prompt = self._get_system_prompt()
        user_prompt = self._build_prompt(idea, memory_context)

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.2
            )
            
            raw_content = response.choices[0].message.content or "{}"
            plan = self._parse_llm_response(raw_content, idea, project_id)

        except Exception as e:
            logger.error(f"LLM API call failed or returned invalid response during planning: {e}")
            plan = self._fallback_plan(idea, project_id)

        if self.memory_manager:
            try:
                self.memory_manager.save_context(
                    project_id=project_id,
                    idea=idea,
                    status="planned",
                    context={"plan": plan.model_dump()}
                )
                self.memory_manager.record_step(
                    project_id=project_id,
                    step_name="planning",
                    status="completed",
                    details={"task_count": len(plan.tasks), "file_count": len(plan.file_structure)}
                )
            except Exception as e:
                logger.warning(f"Failed to record plan context in memory manager: {e}")

        logger.info(f"Successfully generated project plan for '{project_id}' with {len(plan.tasks)} tasks.")
        return plan

    def _parse_llm_response(self, raw_content: str, idea: str, project_id: str) -> ProjectPlan:
        cleaned_content = raw_content.strip()
        if cleaned_content.startswith("```json"):
            cleaned_content = cleaned_content[7:]
        if cleaned_content.startswith("```"):
            cleaned_content = cleaned_content[3:]
        if cleaned_content.endswith("```"):
            cleaned_content = cleaned_content[:-3]
        cleaned_content = cleaned_content.strip()

        try:
            data = json.loads(cleaned_content)
            data["project_id"] = project_id
            if not data.get("idea"):
                data["idea"] = idea
            return ProjectPlan(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error(f"Failed to parse LLM response into ProjectPlan schema: {e}")
            return self._fallback_plan(idea, project_id)

    def _fallback_plan(self, idea: str, project_id: str) -> ProjectPlan:
        logger.warning(f"Constructing fallback project plan for '{project_id}'.")
        return ProjectPlan(
            project_id=project_id,
            idea=idea,
            summary="Fallback REST API solution using FastAPI and SQLite.",
            architecture="Modular FastAPI application with JWT authentication, SQLite database, and Docker containerization.",
            file_structure=[
                "requirements.txt",
                "app/main.py",
                "app/config.py",
                "app/db.py",
                "app/auth.py",
                "Dockerfile",
                "README.md"
            ],
            tasks=[
                TaskStep(
                    task_id="task_1",
                    title="Initialize requirements and configuration",
                    description="Create requirements.txt with FastAPI, Uvicorn, PyJWT, and Pydantic dependencies, along with app/config.py.",
                    file_path="requirements.txt",
                    action="create_file",
                    dependencies=[]
                ),
                TaskStep(
                    task_id="task_2",
                    title="Setup database module",
                    description="Create app/db.py with SQLite database connection and initialization logic.",
                    file_path="app/db.py",
                    action="create_file",
                    dependencies=["task_1"]
                ),
                TaskStep(
                    task_id="task_3",
                    title="Setup authentication & JWT handler",
                    description="Create app/auth.py providing password hashing and JWT token generation/validation.",
                    file_path="app/auth.py",
                    action="create_file",
                    dependencies=["task_1"]
                ),
                TaskStep(
                    task_id="task_4",
                    title="Create main application API endpoints",
                    description="Create app/main.py with FastAPI instance and /login endpoint.",
                    file_path="app/main.py",
                    action="create_file",
                    dependencies=["task_2", "task_3"]
                ),
                TaskStep(
                    task_id="task_5",
                    title="Create Dockerfile and documentation",
                    description="Create Dockerfile for Hugging Face Spaces / Container deployment and a detailed README.md.",
                    file_path="Dockerfile",
                    action="create_file",
                    dependencies=["task_4"]
                )
            ],
            environment_variables={
                "SECRET_KEY": "supersecretkey_change_in_production",
                "ALGORITHM": "HS256"
            },
            dependencies=["fastapi", "uvicorn", "pyjwt", "passlib", "pydantic"]
        )
