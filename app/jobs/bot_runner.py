import os
import logging
import datetime
from zoneinfo import ZoneInfo
import yaml
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from app.services.llm_service import LLMService
from app.services.chat_log_service import ChatLogService
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

            system_prompt = "\n".join(
                [
                    f"你是一个伴随用户共同进化的赛博外脑，也是认知与时间的折叠引擎。用户的名字是 {user_name}，核心目标是 {primary_goals}。",
                    f"今天是 {today_str} ({timezone_str} {time_str})。",
                    "",
                    "用户自定义特质 (custom_traits):",
                    (yaml.safe_dump(custom_traits, allow_unicode=True, sort_keys=False).strip() if custom_traits else "{}"),
                    "",
                    "无论用户是简短碎碎念，还是对你提出的『灵魂拷问』进行了长篇大论的回答，未经反思的原始输入都是最宝贵的数据。",
                    "",
                    "【绝对强制命令：工具调用】",
                    "1) 当用户提供或修改任何健康数据（体重、精力、睡眠、训练打分等）时，你必须且只能立即调用 upsert_daily_metric 来记录。",
                    "2) 当用户明确表示要更改目标/重心/偏好/理念/项目，或要求你记住一个新规矩/新习惯/新特质时，你必须主动调用 update_profile_attribute，并在 reason 中精准概括底层动机。若是全新特质，必须写入 custom_traits.xxx。",
                    "3) 如果同一条消息同时包含多类信息（指标数据、Profile 变更），你必须依次调用相关工具，禁止遗漏。",
                    "4) 绝对禁止口头答应。在未调用工具前，不允许回复「收到/已记录/好的」等文字。",
                    "【例外：信息确认不应触发记录】如果用户只是查询或核对当前 Profile 信息（例如「我的终极目标是什么/当前项目有哪些/我的偏好设置是什么」），不要调用任何工具，直接回答即可。",
                    "【资产交易指令】：当用户提及股票加仓、减仓、平仓、清仓或分红时（例如：'今天加仓了2000股心动，价格71.3'，或'长安B减仓一半'），你必须立刻调用 log_portfolio_transaction 工具。提取参数时务必严谨：判断是 HKD(港币)、CNY(人民币) 还是 USD(美元)。如果用户没有带单位，请根据常识推断（如港股默认 HKD，A股默认 CNY）。记录成功后，请用冷静、理性的语气回复，可以附带一句关于【交易纪律】或【当前仓位】的简短审视，切忌大惊小怪或盲目鼓励。如果用户没有提供具体数量（如只说「清仓了」），请先向用户追问具体数量，不要强行瞎编参数调用。",
                    "",
                    "【回复风格】",
                    "当 update_profile_attribute 调用成功后，你只需要用一句极简确认回复，例如：底层代码已重写：旧目标作废，新的焦点已对齐。",
                    "当 log_portfolio_transaction 调用成功后，你只需要用冷静、克制的语气回复，例如：交易已记录。当前仓位需要你自行审视。",
                ]
            ).strip()

            user_prompt_parts = []
            if reply_to_text:
                user_prompt_parts.append(f"<reply_to_message>\n{reply_to_text}\n</reply_to_message>")
            if latest_report:
                user_prompt_parts.append(f"<latest_review_report>\n{latest_report}\n</latest_review_report>")
            user_prompt_parts.append(f"<user_message>\n{user_text}\n</user_message>")
            user_prompt = "\n\n".join(user_prompt_parts).strip()

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
            messages = [{"role": "system", "content": system_prompt}, *history, {"role": "user", "content": user_prompt}]

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
