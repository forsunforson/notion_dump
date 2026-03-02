import os
import logging
import datetime
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from app.services.llm_service import LLMService
from app.utils.context_fetcher import ContextFetcher
from app.skills.metrics_skill import METRICS_SKILL_SCHEMA, upsert_daily_metric

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

        try:
            # Fetch user profile for context
            profile = self.fetcher.get_profile()
            user_name = profile.get("name", user_name)
            primary_goals = profile.get("goals", "improve productivity and health")
            
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

            # Construct system prompt
            system_prompt = (
                f"你是一个全能的私人助理。用户的名字是 {user_name}，核心目标是 {primary_goals}。\n"
                f"今天是 {today_str} ({timezone_str} {time_str})。\n"
                "你可以使用工具来记录用户的健康数据（如体重、睡眠、情绪等）。\n"
                "当用户提供相关数据时，请务必调用工具进行记录。\n"
                "请用简短、友好的风格回复用户的消息。"
            )

            # Call LLM
            tools = [METRICS_SKILL_SCHEMA]
            tool_map = {"upsert_daily_metric": upsert_daily_metric}
            
            reply_text = await self.llm.ask_with_tools(system_prompt, user_text, tools, tool_map)

            # Send reply
            if reply_text:
                await update.message.reply_text(reply_text)
                logger.info(f"Sent reply to {user_name}")
            else:
                 logger.warning("LLM returned empty response")
                 await update.message.reply_text("抱歉，我没有听清楚，请再说一遍。")

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            await update.message.reply_text("抱歉，我的大脑刚刚走神了，请再说一遍")

    def start_polling(self):
        app = ApplicationBuilder().token(self.token).build()
        
        # Add handler for text messages that are not commands
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        logger.info("Starting Telegram Bot Polling...")
        app.run_polling()
