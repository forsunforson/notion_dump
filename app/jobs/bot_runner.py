import os
import logging
import asyncio
import datetime
import time
from pathlib import Path
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from telegram.error import NetworkError, RetryAfter, TimedOut
from app.services.llm_service import LLMService
from app.services.chat_log_service import ChatLogService
from app.services.prompt_manager import PromptManager
from app.services.context_fetcher import ContextFetcher
from app.skills.metrics_skill import METRICS_SKILL_SCHEMA, upsert_daily_metric
from app.skills.update_profile_skill import UPDATE_PROFILE_SKILL_SCHEMA, update_profile_attribute
from app.skills.update_manual_asset_skill import UPDATE_MANUAL_ASSET_SCHEMA, update_manual_asset_value
from app.skills.update_portfolio_skill import LOG_PORTFOLIO_TRANSACTION_SCHEMA, log_portfolio_transaction
from app.skills.context_collect_skill import COLLECT_MARKDOWN_CONTEXT_SCHEMA, collect_markdown_context
from app.skills.periodic_review_skill import (
    GENERATE_WEEKLY_REVIEW_SCHEMA,
    generate_weekly_review,
    GENERATE_MONTHLY_REVIEW_SCHEMA,
    generate_monthly_review,
)
from app.utils.text_chunking import split_text_smart

logger = logging.getLogger(__name__)

HELP_TEXT = """可用命令：
/help - 显示当前支持的命令列表
/bot - 检查 Telegram Bot 是否在线
/sync - 立即执行一次同步任务
/morning - 立即执行 Morning Routine
/weekly - 立即生成并返回上一完整周周报（周一到周日）
/monthly - 立即生成并返回月报
/month - `/monthly` 的别名
/portfolio - 立即执行 Portfolio Sync
/index - 全量重建 notion_output/index.json
/bot_log - 输出 `./logs/bot.log` 最后 100 行
/execution_log - 输出 `./logs/execution.log` 最后 100 行
""".strip()

def _prefer_review_tool_output(
    reply_text: str | None,
    *,
    executed: dict[str, int],
    tool_outputs: dict[str, str],
) -> str:
    final_reply = reply_text or "抱歉，我没有听清楚，请再说一遍。"
    if executed.get("generate_monthly_review", 0) > 0:
        out = (tool_outputs.get("generate_monthly_review") or "").strip()
        if out:
            return out
    if executed.get("generate_weekly_review", 0) > 0:
        out = (tool_outputs.get("generate_weekly_review") or "").strip()
        if out:
            return out
    return final_reply

class TelegramBotRunner:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")
        
        self.allowed_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not self.allowed_chat_id:
            logger.error("TELEGRAM_CHAT_ID environment variable is not set. Bot will NOT respond to any messages.")
            self.allowed_chat_id = None
        else:
            try:
                self.allowed_chat_id = int(self.allowed_chat_id)
            except ValueError:
                logger.error(f"Invalid TELEGRAM_CHAT_ID: {self.allowed_chat_id}. Bot will NOT respond to any messages.")
                self.allowed_chat_id = None

        self.llm = LLMService()
        self.fetcher = ContextFetcher()
        self.chat_log = ChatLogService()
        self.prompt_manager = PromptManager()
        self._history_by_chat: dict[int, list[dict]] = {}
        logger.info("TelegramBotRunner initialized")

    @staticmethod
    def _logs_dir() -> Path:
        return Path(__file__).resolve().parents[2] / "logs"

    @classmethod
    def _read_log_tail(cls, filename: str, line_count: int = 100) -> str:
        path = cls._logs_dir() / filename
        if not path.exists():
            return f"⚠️ Log file not found: {path}"
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception as e:
            return f"❌ Failed to read log file {path}: {e}"
        tail = lines[-line_count:]
        if not tail:
            return f"ℹ️ Log file is empty: {path}"
        content = "\n".join(tail)
        return f"{path.name} last {min(line_count, len(lines))} lines:\n```text\n{content}\n```"

    async def handle_message(self, update: Update, _context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return

        # Security check: verify chat_id
        current_chat_id = update.effective_chat.id
        if self.allowed_chat_id is None or current_chat_id != self.allowed_chat_id:
            logger.warning(f"Unauthorized access attempt from chat_id: {current_chat_id}")
            return

        user_text = update.message.text
        user_name = update.effective_user.first_name if update.effective_user else "User"
        
        logger.info(f"Received message from {user_name}: {user_text}")
        self.chat_log.log_message(role="User", content=user_text)

        try:
            # Fast path: explicit slash commands for ops tasks
            cmd = (user_text or "").strip().split()[0].lower()
            if cmd in {"/help", "/sync", "/morning", "/weekly", "/month", "/monthly", "/portfolio", "/index", "/bot", "/bot_log", "/execution_log"}:
                try:
                    if cmd == "/help":
                        await update.message.reply_text(HELP_TEXT)
                        return
                    if cmd == "/bot":
                        await update.message.reply_text("✅ Telegram Bot is online.")
                        return
                    if cmd == "/sync":
                        from main import run_sync_job
                        await run_sync_job()
                        await update.message.reply_text("✅ Sync completed.")
                        return
                    if cmd == "/morning":
                        from app.jobs.routines import DailyRoutines
                        ok = await DailyRoutines().morning_routine()
                        await update.message.reply_text("✅ Morning routine completed." if ok else "⚠️ Morning routine finished with issues.")
                        return
                    if cmd in ("/weekly",):
                        md = await generate_weekly_review(period="previous")
                        parts = split_text_smart(md or "", max_chars=3500)
                        for i, part in enumerate(parts or ["（空）"]):
                            await update.message.reply_text(part)
                            if i < len(parts) - 1:
                                await asyncio.sleep(1)
                        return
                    if cmd in ("/monthly", "/month"):
                        md = await generate_monthly_review()
                        parts = split_text_smart(md or "", max_chars=3500)
                        for i, part in enumerate(parts or ["（空）"]):
                            await update.message.reply_text(part)
                            if i < len(parts) - 1:
                                await asyncio.sleep(1)
                        return
                    if cmd == "/portfolio":
                        from main import run_portfolio_job
                        await asyncio.get_running_loop().run_in_executor(None, run_portfolio_job)
                        await update.message.reply_text("✅ Portfolio sync completed.")
                        return
                    if cmd == "/index":
                        # Rule-based full rebuild for stability
                        from app.services.index_generator import IndexGeneratorService
                        svc = IndexGeneratorService()
                        data = await svc.rebuild_all()
                        await update.message.reply_text(f"✅ Index rebuilt. {len(data)} files indexed.")
                        return
                    if cmd == "/bot_log":
                        log_text = self._read_log_tail("bot.log")
                        parts = split_text_smart(log_text, max_chars=3500) or ["（空）"]
                        for i, part in enumerate(parts):
                            await update.message.reply_text(part)
                            if i < len(parts) - 1:
                                await asyncio.sleep(1)
                        return
                    if cmd == "/execution_log":
                        log_text = self._read_log_tail("execution.log")
                        parts = split_text_smart(log_text, max_chars=3500) or ["（空）"]
                        for i, part in enumerate(parts):
                            await update.message.reply_text(part)
                            if i < len(parts) - 1:
                                await asyncio.sleep(1)
                        return
                except Exception as e:
                    logger.exception("Slash command execution failed")
                    await update.message.reply_text(f"❌ Command failed: {e}")
                    return

            # Fetch user profile for context
            profile = self.fetcher.get_profile()
            user_name = profile.get("name", user_name)
            physical_baseline = profile.get("physical_baseline", {}) if isinstance(profile.get("physical_baseline", {}), dict) else {}
            primary_goals = physical_baseline.get("primary_goals", "improve productivity and health")
            custom_traits = profile.get("custom_traits", {}) if isinstance(profile.get("custom_traits", {}), dict) else {}
            
            # Get current time based on user's timezone preference
            preferences = profile.get("preferences", {})
            timezone_str = preferences.get("timezone", "Asia/Shanghai")
            try:
                tz = ZoneInfo(timezone_str)
            except Exception:
                tz = ZoneInfo("Asia/Shanghai")
                
            now_local = datetime.datetime.now(tz)
            today_str = now_local.strftime("%Y-%m-%d")
            time_str = now_local.strftime("%H:%M")

            reply_to_text = ""
            if update.message.reply_to_message and update.message.reply_to_message.text:
                reply_to_text = update.message.reply_to_message.text

            latest_report = self.fetcher.get_latest_report()

            executed = {
                "upsert_daily_metric": 0,
                "update_profile_attribute": 0,
                "update_manual_asset_value": 0,
                "log_portfolio_transaction": 0,
                "collect_markdown_context": 0,
                "generate_weekly_review": 0,
                "generate_monthly_review": 0,
            }
            tool_outputs: dict[str, str] = {}

            def wrapped_upsert_daily_metric(**kwargs) -> str:
                executed["upsert_daily_metric"] += 1
                return upsert_daily_metric(**kwargs)

            def wrapped_update_profile_attribute(**kwargs) -> str:
                executed["update_profile_attribute"] += 1
                return update_profile_attribute(**kwargs)

            def wrapped_update_manual_asset_value(**kwargs) -> str:
                executed["update_manual_asset_value"] += 1
                return update_manual_asset_value(**kwargs)

            def wrapped_log_portfolio_transaction(**kwargs) -> str:
                executed["log_portfolio_transaction"] += 1
                return log_portfolio_transaction(**kwargs)

            def wrapped_collect_markdown_context(**kwargs) -> str:
                executed["collect_markdown_context"] += 1
                return collect_markdown_context(**kwargs)

            async def wrapped_generate_weekly_review(**kwargs):
                executed["generate_weekly_review"] += 1
                out = await generate_weekly_review(**kwargs)
                tool_outputs["generate_weekly_review"] = str(out or "")
                return out

            async def wrapped_generate_monthly_review(**kwargs):
                executed["generate_monthly_review"] += 1
                out = await generate_monthly_review(**kwargs)
                tool_outputs["generate_monthly_review"] = str(out or "")
                return out

            tools = [
                METRICS_SKILL_SCHEMA,
                UPDATE_PROFILE_SKILL_SCHEMA,
                UPDATE_MANUAL_ASSET_SCHEMA,
                LOG_PORTFOLIO_TRANSACTION_SCHEMA,
                COLLECT_MARKDOWN_CONTEXT_SCHEMA,
                GENERATE_WEEKLY_REVIEW_SCHEMA,
                GENERATE_MONTHLY_REVIEW_SCHEMA,
            ]
            tool_map = {
                "upsert_daily_metric": wrapped_upsert_daily_metric,
                "update_profile_attribute": wrapped_update_profile_attribute,
                "update_manual_asset_value": wrapped_update_manual_asset_value,
                "log_portfolio_transaction": wrapped_log_portfolio_transaction,
                "collect_markdown_context": wrapped_collect_markdown_context,
                "generate_weekly_review": wrapped_generate_weekly_review,
                "generate_monthly_review": wrapped_generate_monthly_review,
            }

            chat_id = update.effective_chat.id
            history = self._history_by_chat.get(chat_id, [])
            messages = self.prompt_manager.build_telegram_bot_messages(
                history=history,
                user_text=user_text,
                reply_to_text=reply_to_text,
                latest_report=latest_report,
                user_name=user_name,
                primary_goals=primary_goals,
                timezone_str=timezone_str,
                today_str=today_str,
                time_str=time_str,
                custom_traits=custom_traits,
            )

            reply_text, _ = await self.llm.ask_with_tools_messages(messages, tools, tool_map)

            final_reply = _prefer_review_tool_output(reply_text, executed=executed, tool_outputs=tool_outputs)

            stored_reply = final_reply
            if len(stored_reply) > 1200:
                stored_reply = stored_reply[:1200].rstrip() + "\n(…截断)"
            new_history = [*history, {"role": "user", "content": user_text}, {"role": "assistant", "content": stored_reply}]
            self._history_by_chat[chat_id] = new_history[-20:]

            # Send reply
            if not reply_text:
                logger.warning("LLM returned empty response")
            self.chat_log.log_message(role="Bot", content=final_reply)
            parts = split_text_smart(final_reply, max_chars=3500)
            if not parts:
                parts = ["（空响应）"]
            for i, part in enumerate(parts):
                await update.message.reply_text(part)
                if i < len(parts) - 1:
                    await asyncio.sleep(1)
            logger.info(f"Sent reply to {user_name}")

        except Exception:
            logger.exception("Error handling message")
            final_reply = "请求失败：大模型调用异常或处理链路中断。"
            self.chat_log.log_message(role="Bot", content=final_reply)
            await update.message.reply_text(final_reply)
            raise

    def start_polling(self):
        backoff_s = 1
        max_backoff_s = 60
        while True:
            try:
                app = (
                    ApplicationBuilder()
                    .token(self.token)
                    .connect_timeout(15)
                    .read_timeout(45)
                    .write_timeout(45)
                    .pool_timeout(30)
                    .get_updates_connect_timeout(15)
                    .get_updates_read_timeout(90)
                    .get_updates_write_timeout(45)
                    .get_updates_pool_timeout(30)
                    .build()
                )

                app.add_handler(MessageHandler(filters.TEXT, self.handle_message))

                logger.info("Starting Telegram Bot Polling...")
                app.run_polling()
                backoff_s = 1
            except RetryAfter as e:
                sleep_s = max(1, int(getattr(e, "retry_after", 1))) + 1
                logger.warning(f"Telegram rate-limited. Sleeping {sleep_s}s before retry.")
                time.sleep(sleep_s)
                continue
            except (NetworkError, TimedOut) as e:
                logger.warning(f"Telegram polling network error: {e}. Retrying in {backoff_s}s.")
                time.sleep(backoff_s)
                backoff_s = min(max_backoff_s, backoff_s * 2)
                continue
            except (KeyboardInterrupt, SystemExit):
                raise
