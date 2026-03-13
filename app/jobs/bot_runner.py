import os
import logging
import datetime
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from app.services.llm_service import LLMService
from app.services.chat_log_service import ChatLogService
from app.services.prompt_manager import PromptManager
from app.utils.context_fetcher import ContextFetcher
from app.skills.metrics_skill import METRICS_SKILL_SCHEMA, upsert_daily_metric
from app.skills.update_profile_skill import UPDATE_PROFILE_SKILL_SCHEMA, update_profile_attribute
from app.skills.update_portfolio_skill import LOG_PORTFOLIO_TRANSACTION_SCHEMA, log_portfolio_transaction

logger = logging.getLogger(__name__)

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

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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

            executed = {"upsert_daily_metric": 0, "update_profile_attribute": 0, "log_portfolio_transaction": 0}

            def wrapped_upsert_daily_metric(**kwargs) -> str:
                executed["upsert_daily_metric"] += 1
                return upsert_daily_metric(**kwargs)

            def wrapped_update_profile_attribute(**kwargs) -> str:
                executed["update_profile_attribute"] += 1
                return update_profile_attribute(**kwargs)

            def wrapped_log_portfolio_transaction(**kwargs) -> str:
                executed["log_portfolio_transaction"] += 1
                return log_portfolio_transaction(**kwargs)

            tools = [METRICS_SKILL_SCHEMA, UPDATE_PROFILE_SKILL_SCHEMA, LOG_PORTFOLIO_TRANSACTION_SCHEMA]
            tool_map = {
                "upsert_daily_metric": wrapped_upsert_daily_metric,
                "update_profile_attribute": wrapped_update_profile_attribute,
                "log_portfolio_transaction": wrapped_log_portfolio_transaction,
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

            new_history = [*history, {"role": "user", "content": user_text}, {"role": "assistant", "content": reply_text or ""}]
            self._history_by_chat[chat_id] = new_history[-20:]

            # Send reply
            final_reply = reply_text or "抱歉，我没有听清楚，请再说一遍。"
            if not reply_text:
                logger.warning("LLM returned empty response")
            self.chat_log.log_message(role="Bot", content=final_reply)
            await update.message.reply_text(final_reply)
            logger.info(f"Sent reply to {user_name}")

        except Exception:
            logger.exception("Error handling message")
            final_reply = "请求失败：大模型调用异常或处理链路中断。"
            self.chat_log.log_message(role="Bot", content=final_reply)
            await update.message.reply_text(final_reply)
            raise

    def start_polling(self):
        app = ApplicationBuilder().token(self.token).build()
        
        # Add handler for text messages that are not commands
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        logger.info("Starting Telegram Bot Polling...")
        app.run_polling()
