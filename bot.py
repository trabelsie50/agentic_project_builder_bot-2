import asyncio
import logging
import os
import sys
from typing import Any, Dict, Optional, Union

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import settings
from db import init_db
from memory_manager import MemoryManager
from orchestrator import WorkflowOrchestrator

# Configure logger
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("bot")


def is_user_allowed(user_id: int) -> bool:
    """Check if the user is authorized to interact with the bot."""
    allowed_users = settings.get_allowed_users_list()
    if not allowed_users:
        return True
    return user_id in allowed_users


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message when the command /start is issued."""
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id
    if not is_user_allowed(user_id):
        await update.message.reply_text(
            "⚠️ عذراً، غير مصرح لك باستخدام هذا البوت."
        )
        return

    welcome_text = (
        "👋 أهلاً بك في بوت تطوير المشاريع الذكي (Agentic Project Builder Bot)!\n\n"
        "🤖 أنا نظام وكلاء متكامل يعتمد على الذكاء الاصطناعي لبناء المشاريع البرمجية البرمجية بالكامل.\n\n"
        "💡 كيف تعمل؟\n"
        "1. أرسل فكرة المشروع البرمجي في رسالة واحدة.\n"
        "2. سيقوم وكيل التخطيط بتفكيك الفكرة وإعداد خطة شاملة.\n"
        "3. سيقوم وكيل التوليد والتنفيذ بكتابة الملفات وتجربتها وتصحيح الأخطاء ذاتياً.\n"
        "4. سيتم حفظ الأخطاء في سجل الذاكرة لتفاديها مستقبلاً.\n"
        "5. سيتم رفع المستودع تلقائياً إلى GitHub وتسليمك رابط المشروع ومخرجاته.\n\n"
        "📌 الأوامر المتاحة:\n"
        "/start - البدء وتثبيت التعليمات\n"
        "/help - تعليمات كيفية كتابة الأفكار بشكل موجه\n"
        "/history - استعراض سجل الذاكرة والأخطاء المسجلة"
    )
    await update.message.reply_text(welcome_text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send help instructions."""
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id
    if not is_user_allowed(user_id):
        await update.message.reply_text("⚠️ عذراً، غير مصرح لك باستخدام هذا البوت.")
        return

    help_text = (
        "📖 دليل استخدام البوت:\n\n"
        "أفضل طريقة لإعطاء الفكرة هي تقديم وصف شامل يتضمن:\n"
        "- نوع المشروع (مثال: REST API بـ FastAPI أو Bot أو CLI Tool).\n"
        "- التقنيات المطلوبة (مثال: SQLite, JWT Authentication).\n"
        "- نقاط النهاية (Endpoints) الأساسية.\n\n"
        "مثال ممتاذ:\n"
        "\"أريد بناء تطبيق REST API بـ FastAPI لنظام تسجيل الدخول باستعمال SQLite و JWT، يحتوي على نقطة نهاية /login ونقطة /register مع التوثيق الكامل.\"\n\n"
        "أرسل فكرتك الآن في رسالة وسأبدأ بالعمل فوراً! 🚀"
    )
    await update.message.reply_text(help_text)


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show system memory and past error logs."""
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id
    if not is_user_allowed(user_id):
        await update.message.reply_text("⚠️ عذراً، غير مصرح لك باستخدام هذا البوت.")
        return

    await update.message.reply_text("🔍 جاري جلب سجل الذاكرة والأخطاء المصححة...")

    memory_mgr = MemoryManager()

    try:
        resolved_errors = memory_mgr.get_all_resolved_errors(limit=5)
        if not resolved_errors:
            await update.message.reply_text(
                "ℹ️ لا توجد أخطاء مسجلة أو محلولة سابقاً في الذاكرة حالياً."
            )
            return

        report = "🧠 **سجل الذاكرة والتعلم من الأخطاء:**\n\n"
        for idx, err in enumerate(resolved_errors, start=1):
            project_id = err.get("project_id", "عام")
            err_type = err.get("error_type", "Unknown")
            err_msg = err.get("error_message", "No message")
            resolution = err.get("resolution", "تم الحل")

            report += f"**{idx}. مشروع: {project_id}**\n"
            report += f"نوع الخطأ: `{err_type}`\n"
            report += f"الخطأ: `{err_msg[:100]}`\n"
            report += f"التصحيح: {resolution}\n"
            report += "---------------------\n"

        await update.message.reply_text(report, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error fetching memory history: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء جلب سجل الذاكرة.")


async def handle_project_idea(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle incoming user messages containing project ideas."""
    if not update.effective_user or not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    if not is_user_allowed(user_id):
        await update.message.reply_text("⚠️ عذراً، غير مصرح لك باستخدام هذا البوت.")
        return

    idea_text = update.message.text.strip()

    if idea_text.startswith("/"):
        return

    chat_id = update.effective_chat.id if update.effective_chat else user_id

    await update.message.reply_text(
        f"🚀 تم استقبال فكرتك بنجاح!\n\n"
        f"📝 الفكرة: {idea_text}\n\n"
        f"⚙️ يتم الآن تشغيل نظام الوكلاء المزدوج للبدء بالتخطيط والتنفيذ..."
    )

    loop = asyncio.get_running_loop()

    def sync_progress_callback(data: Union[str, Dict[str, Any]]) -> None:
        if isinstance(data, dict):
            msg = data.get("message") or str(data)
        else:
            msg = str(data)

        asyncio.run_coroutine_threadsafe(
            context.bot.send_message(chat_id=chat_id, text=f"🔄 {msg}"),
            loop,
        )

    def run_orchestrator_task() -> Dict[str, Any]:
        orchestrator = WorkflowOrchestrator()
        return orchestrator.execute_workflow(
            idea=idea_text,
            deploy=True,
            private_repo=False,
            progress_callback=sync_progress_callback,
        )

    try:
        result = await loop.run_in_executor(None, run_orchestrator_task)

        status = result.get("status", "unknown")
        project_id = result.get("project_id", "N/A")
        github_url = result.get("github_url")
        summary = result.get("summary", {})

        if status == "success":
            reply_msg = (
                f"✅ **تم إنشاء وتطوير المشروع بنجاح!** 🎉\n\n"
                f"🆔 **معرف المشروع:** `{project_id}`\n"
            )

            if github_url:
                reply_msg += f"🔗 **رابط المستودع على GitHub:**\n{github_url}\n\n"

            files_created = summary.get("files_created", [])
            if files_created:
                reply_msg += f"📁 **الملفات التي تم إنشاؤها ({len(files_created)}):**\n"
                for f in files_created[:10]:
                    reply_msg += f"- `{f}`\n"
                if len(files_created) > 10:
                    reply_msg += f"- و {len(files_created) - 10} ملفات أخرى...\n"

            errors_fixed = summary.get("errors_fixed", 0)
            reply_msg += f"\n🛠️ **عدد الأخطاء التي تم تصحيحها تلقائياً:** {errors_fixed}\n"
            reply_msg += "\n📄 المستودع جاهز ويمكنك تشغيله مباشرة أو رفعه إلى HuggingFace Spaces!"

            await context.bot.send_message(
                chat_id=chat_id, text=reply_msg, parse_mode="Markdown"
            )
        else:
            error_details = result.get("error", "حدث خطأ غير معروف أثناء التنفيذ.")
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"❌ **فشلت عملية تطوير المشروع.**\n\n"
                    f"🆔 المعرف: `{project_id}`\n"
                    f"⚠️ السبب: {error_details}"
                ),
                parse_mode="Markdown",
            )

    except Exception as e:
        logger.exception("Error executing workflow from bot")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"💥 حدث خطأ غير متوقع أثناء معالجة الطلب: {str(e)}",
        )


def run_bot() -> None:
    """Initialize database and run Telegram Bot polling."""
    settings.setup_directories()

    try:
        asyncio.run(init_db())
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")

    token = settings.TELEGRAM_BOT_TOKEN
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.error(
            "TELEGRAM_BOT_TOKEN is not set or invalid in configuration. Exiting."
        )
        sys.exit(1)

    logger.info("Starting Telegram Bot Application...")
    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_project_idea)
    )

    logger.info("Bot is polling for updates...")
    application.run_polling(drop_pending_updates=True)


def main() -> None:
    """Main entry point."""
    run_bot()


if __name__ == "__main__":
    main()
