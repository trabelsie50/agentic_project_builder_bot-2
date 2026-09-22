import asyncio
import inspect
import logging
import os
import re
import traceback
import uuid
from typing import Any, Callable, Dict, List, Optional, Union

from config import Settings, settings
from db import init_db
from memory_manager import MemoryManager
from planner_agent import PlannerAgent, ProjectPlan, TaskStep
from code_generator import CodeGeneratorAgent, ExecutionResult
from git_deployer import GitDeployer

logger = logging.getLogger(__name__)


class WorkflowOrchestrator:
    """
    المحرك الأساسي لربط كافة الوكلاء والذاكرة وإدارة تدفق العمل الذاتي،
    والتصحيح التلقائي، وتجهيز التقارير النهائية للمشاريع.
    """

    def __init__(
        self,
        memory_manager: Optional[MemoryManager] = None,
        planner: Optional[PlannerAgent] = None,
        code_generator: Optional[CodeGeneratorAgent] = None,
        deployer: Optional[GitDeployer] = None,
    ):
        self.memory_manager = memory_manager or MemoryManager()
        self.planner = planner or PlannerAgent(memory_manager=self.memory_manager)
        self.code_generator = code_generator or CodeGeneratorAgent(memory_manager=self.memory_manager)
        self.deployer = deployer or GitDeployer()

    async def _notify_progress(
        self,
        callback: Optional[Callable[[str], Any]],
        message: str
    ) -> None:
        """إرسال التحديثات اللحظية عبر الدالة الممررة إن وجدت."""
        if callback:
            try:
                if inspect.iscoroutinefunction(callback):
                    await callback(message)
                else:
                    callback(message)
            except Exception as e:
                logger.warning(f"Error in progress callback notification: {e}")

    def _sanitize_project_id(self, raw_id: str) -> str:
        """تنظيف واستخلاص اسم محدد وصالح للمشروع والمستودع."""
        clean = re.sub(r'[^a-zA-Z0-9_-]', '_', raw_id)
        clean = clean.strip('_')
        return clean if clean else f"proj_{uuid.uuid4().hex[:8]}"

    def _get_project_dir(self, project_id: str) -> str:
        """تحديد وإنشاء المسار المحلي الخاص بملفات المشروع."""
        if hasattr(settings, 'WORKSPACE_DIR'):
            base_workspace = settings.WORKSPACE_DIR
        elif hasattr(settings, 'BASE_DIR'):
            base_workspace = os.path.join(str(settings.BASE_DIR), "workspace")
        else:
            base_workspace = os.path.join(os.getcwd(), "workspace")

        project_dir = os.path.join(str(base_workspace), project_id)
        os.makedirs(project_dir, exist_ok=True)
        return project_dir

    async def execute_workflow(
        self,
        idea: str,
        project_id: Optional[str] = None,
        deploy: bool = True,
        private_repo: bool = True,
        progress_callback: Optional[Callable[[str], Any]] = None,
    ) -> Dict[str, Any]:
        """
        تنفيذ مسار العمل الكامل بدءاً من استقبال الفكرة، والتخطيط،
        وتوليد الأكواد بالتصحيح الذاتي، والنشر التلقائي، وصولاً للتقرير النهائي.
        """
        if hasattr(settings, "setup_directories"):
            try:
                settings.setup_directories()
            except Exception as e:
                logger.warning(f"Could not setup directories: {e}")

        try:
            await init_db()
        except Exception as e:
            logger.warning(f"Database initialization warning: {e}")

        if not project_id:
            project_id = f"proj_{uuid.uuid4().hex[:8]}"
        else:
            project_id = self._sanitize_project_id(project_id)

        project_dir = self._get_project_dir(project_id)

        logger.info(f"Starting workflow for project '{project_id}' at: {project_dir}")
        await self._notify_progress(
            progress_callback,
            f"🚀 **بدء معالجة الفكرة البرمجية**\nمعرّف المشروع: `{project_id}`"
        )

        # 1. تهيئة الذاكرة وحفظ السياق الأولي
        try:
            self.memory_manager.save_context(
                project_id=project_id,
                idea=idea,
                status="planning",
                context={"idea": idea, "project_dir": project_dir}
            )
            self.memory_manager.record_step(
                project_id=project_id,
                step_name="workflow_start",
                status="success",
                details={"idea": idea}
            )
        except Exception as e:
            logger.error(f"Error initializing project context in memory: {e}")

        # 2. التخطيط المعتمد على وكيل التخطيط PlannerAgent
        await self._notify_progress(
            progress_callback,
            "🧠 **جاري تحليل الفكرة وتقسيم المهام وتحديد البنية التحتية...**"
        )
        try:
            plan = self.planner.plan_project(idea=idea, project_id=project_id)
            task_count = len(plan.tasks) if plan and hasattr(plan, 'tasks') and plan.tasks else 0

            self.memory_manager.record_step(
                project_id=project_id,
                step_name="planning_completed",
                status="success",
                details={"task_count": task_count}
            )

            plan_dict = plan.model_dump() if hasattr(plan, "model_dump") else plan.dict()
            self.memory_manager.save_context(
                project_id=project_id,
                idea=idea,
                status="coding",
                context={"plan": plan_dict}
            )

            await self._notify_progress(
                progress_callback,
                f"📋 **تم إنشاء خطة العمل بنجاح!**\n• عدد المهام: `{task_count}`\n• إطار العمل: `{plan.framework}`\n• المعمارية: `{plan.architecture}`"
            )
        except Exception as e:
            error_msg = f"فشل وكيل التخطيط: {str(e)}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            self.memory_manager.record_error(
                project_id=project_id,
                error_type="planner_error",
                error_message=str(e),
                code_context=traceback.format_exc()
            )
            self.memory_manager.record_step(
                project_id=project_id,
                step_name="planning_failed",
                status="failed",
                details={"error": str(e)}
            )
            await self._notify_progress(
                progress_callback,
                f"❌ **حدث خطأ أثناء مرحلة التخطيط:** {str(e)}"
            )
            return {
                "status": "failed",
                "project_id": project_id,
                "error": str(e),
                "step": "planning"
            }

        # 3. توليد الأكواد والتصحيح الذاتي المعتمد على CodeGeneratorAgent
        await self._notify_progress(
            progress_callback,
            "💻 **جاري توليد الأكواد وإنشاء الملفات مع حلقة الاختبار والتصحيح الذاتي...**"
        )
        gen_results: List[ExecutionResult] = []
        try:
            gen_results = self.code_generator.generate_project_files(
                project_id=project_id,
                plan=plan,
                project_dir=project_dir,
                max_retries=3
            )

            successful_tasks = [r for r in gen_results if r.success]
            failed_tasks = [r for r in gen_results if not r.success]

            self.memory_manager.record_step(
                project_id=project_id,
                step_name="code_generation_completed",
                status="success" if len(failed_tasks) == 0 else "partial_success",
                details={
                    "total": len(gen_results),
                    "successful": len(successful_tasks),
                    "failed": len(failed_tasks)
                }
            )

            await self._notify_progress(
                progress_callback,
                f"⚙️ **انتهت مرحلة التوليد:**\n• الملفات الناجحة: `{len(successful_tasks)}/{len(gen_results)}`"
            )
        except Exception as e:
            error_msg = f"فشل وكيل توليد الكود: {str(e)}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            self.memory_manager.record_error(
                project_id=project_id,
                error_type="code_generation_error",
                error_message=str(e),
                code_context=traceback.format_exc()
            )
            self.memory_manager.record_step(
                project_id=project_id,
                step_name="code_generation_failed",
                status="failed",
                details={"error": str(e)}
            )
            await self._notify_progress(
                progress_callback,
                f"❌ **حدث خطأ أثناء توليد الكود:** {str(e)}"
            )
            return {
                "status": "failed",
                "project_id": project_id,
                "error": str(e),
                "step": "code_generation",
                "plan": plan
            }

        # 4. إدارة النسخ المخبأة والنشر التلقائي Git / GitHub
        deploy_results: Dict[str, Any] = {"success": False, "message": "Deploy skipped"}
        if deploy:
            await self._notify_progress(
                progress_callback,
                "📦 **جاري تهيئة مستودع Git والرفع التلقائي إلى GitHub...**"
            )
            try:
                repo_name = f"agent-{project_id}"
                if hasattr(self.deployer, "deploy_project"):
                    deploy_results = self.deployer.deploy_project(
                        project_dir=project_dir,
                        repo_name=repo_name,
                        private=private_repo
                    )
                elif hasattr(self, "github_manager") and hasattr(self.github_manager, "create_and_push_repo"):
                    deploy_results = await self.github_manager.create_and_push_repo(
                        project_dir=project_dir,
                        repo_name=repo_name,
                        is_private=private_repo
                    )
                else:
                    deploy_results = {"success": False, "error": "Deployer method unavailable"}

                if deploy_results.get("success"):
                    await self._notify_progress(
                        progress_callback,
                        f"✅ **تم نشر المشروع بنجاح على GitHub:** {deploy_results.get('repo_url') or deploy_results.get('html_url')}"
                    )
                else:
                    await self._notify_progress(
                        progress_callback,
                        f"⚠️ **فشل النشر على GitHub:** {deploy_results.get('error', 'سبب غير معروف')}"
                    )
            except Exception as e:
                logger.error(f"حدث خطأ أثناء النشر على GitHub: {str(e)}")
                deploy_results = {"success": False, "error": str(e)}
                await self._notify_progress(
                    progress_callback,
                    f"⚠️ **حدث خطأ أثناء عملية النشر:** {str(e)}"
                )

        # 5. تسجيل إتمام خط الأنابيب بنجاح
        self.memory_manager.record_step(
            project_id=project_id,
            step_name="pipeline_completed",
            status="completed",
            details={
                "project_dir": project_dir,
                "successful_tasks": len(successful_tasks),
                "total_tasks": len(gen_results),
                "deploy": deploy_results
            }
        )

        await self._notify_progress(
            progress_callback,
            "🎉 **تم كتمال جميع مراحل خط الإنتاج وتوليد المشروع بنجاح!**"
        )

        architecture = getattr(plan, "architecture", "") if plan else ""

        return {
            "status": "success",
            "project_id": project_id,
            "project_dir": project_dir,
            "architecture": architecture,
            "plan": plan,
            "code_generation": gen_results,
            "deployment": deploy_results
        }

    async def _notify_progress(
        self,
        callback: Optional[Callable[[Union[str, Dict[str, Any]]], Any]],
        message: Union[str, Dict[str, Any]]
    ) -> None:
        """
        دالة مساعدة لإرسال إشعارات التحديث للمستخدم أو النظام المستدعي.
        """
        if callback is None:
            return
        try:
            if inspect.iscoroutinefunction(callback):
                await callback(message)
            else:
                callback(message)
        except Exception as e:
            logger.warning(f"فشل إرسال تحديث التقدم عبر الدالة المستدعاة: {str(e)}")
