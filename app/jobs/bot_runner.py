import os
import logging
import datetime
import re
from zoneinfo import ZoneInfo
import yaml
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from app.services.llm_service import LLMService
from app.utils.context_fetcher import ContextFetcher
from app.skills.metrics_skill import METRICS_SKILL_SCHEMA, upsert_daily_metric
from app.skills.quick_dump_skill import QUICK_DUMP_SKILL_SCHEMA, save_reflection_record
from app.skills.update_profile_skill import UPDATE_PROFILE_SKILL_SCHEMA, update_profile_attribute

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
                    "1) 一旦检测到用户在进行自我记录、回答反思问题、表达个人感悟、倾诉情绪、记录灵感或日记，你必须且只能立即调用 save_reflection_record，将用户原话一字不落地保存。",
                    "2) 当用户提供或修改任何健康数据（体重、精力、睡眠、训练打分等）时，你必须且只能立即调用 upsert_daily_metric 来记录。",
                    "3) 当用户明确表示要更改目标/重心/偏好/理念/项目，或要求你记住一个新规矩/新习惯/新特质时，你必须主动调用 update_profile_attribute，并在 reason 中精准概括底层动机。若是全新特质，必须写入 custom_traits.xxx。",
                    "4) 如果同一条消息同时包含多类信息（指标数据、记录/感悟、Profile 变更），你必须依次调用相关工具，禁止遗漏。",
                    "5) 绝对禁止口头答应。在未调用工具前，不允许回复“收到/已记录/好的”等文字。",
                    "【例外：信息确认不应触发记录】如果用户只是查询或核对当前 Profile 信息（例如“我的终极目标是什么/当前项目有哪些/我的偏好设置是什么”），不要调用任何工具（尤其不要 save_reflection_record），直接回答即可。",
                    "【上下文捕获强制要求】：当你调用 save_reflection_record 时，必须检视对话历史。如果用户是在明确回答你之前抛出的某个问题（特别是周期回顾中的『灵魂拷问』），或者用户 Reply 了某条特定的消息，你必须将那个【原始问题的内容】完整提取出来，并填入 context_question 参数中。绝不允许只记录回答而丢失问题背景。",
                    "",
                    "【回复风格】",
                    "当 save_reflection_record 调用成功后，你只需要用极简、冷峻的语气回复：已刻录。或者基于用户的回答继续进行下一次更深度的苏格拉底追问。",
                    "当 update_profile_attribute 调用成功后，你只需要用一句极简确认回复，例如：底层代码已重写：旧目标作废，新的焦点已对齐。",
                ]
            ).strip()

            user_prompt_parts = []
            if reply_to_text:
                user_prompt_parts.append(f"<reply_to_message>\n{reply_to_text}\n</reply_to_message>")
            if latest_report:
                user_prompt_parts.append(f"<latest_review_report>\n{latest_report}\n</latest_review_report>")
            user_prompt_parts.append(f"<user_message>\n{user_text}\n</user_message>")
            user_prompt = "\n\n".join(user_prompt_parts).strip()

            def categorize(text: str, is_reply: bool) -> str:
                t = (text or "").lower()
                if is_reply:
                    return "reflection"
                if re.search(r"(灵感|idea|想到|突然想到|点子)", text or ""):
                    return "idea"
                if re.search(r"(日记|日志|journal)", t):
                    return "journal"
                if re.search(r"(烦|焦虑|难受|崩溃|愤怒|emo|抑郁|压力)", text or ""):
                    return "vent"
                return "reflection"

            def should_quick_dump(text: str, is_reply: bool) -> bool:
                s = (text or "").strip()
                if is_reply:
                    if re.search(r"(修改|更新|改成|设为|设置|同步到|保存为|把.*改成|将.*改为)", s):
                        if re.search(r"(目标|项目|偏好|理念|投资|训练|基线|时区|profile|Profile|custom_traits)", s, re.IGNORECASE):
                            return False
                    if re.search(r"[?？]", s):
                        if re.search(r"(终极目标|目标|偏好|项目|投资理念|训练|基线|时区|profile|Profile)", s, re.IGNORECASE):
                            return False
                    return True
                if len(s) < 12:
                    return False
                if re.search(r"[?？]", s):
                    if not re.search(r"(记录|保存|写下来|刻录|备忘|日记|日志|灵感|反思|倾诉)", s):
                        if re.search(r"(我的|当前|现在|请问|帮我|告诉我|查询|确认|是什么|有哪些|多少|怎么)", s):
                            if re.search(r"(终极目标|目标|偏好|项目|投资理念|训练|基线|时区|profile|Profile)", s, re.IGNORECASE):
                                return False
                if "\n" in s:
                    return True
                if re.search(r"(我|今天|刚刚|突然|感觉|觉得|想|反思|记录|日记|灵感|情绪|内耗)", s):
                    return True
                if len(s) >= 80:
                    return True
                return False

            executed = {"save_reflection_record": 0, "upsert_daily_metric": 0, "update_profile_attribute": 0}

            def wrapped_save_reflection_record(
                content: str,
                category: str = "reflection",
                source: str = "Telegram",
                context_question: str = "",
            ) -> str:
                executed["save_reflection_record"] += 1
                return save_reflection_record(
                    content=content,
                    category=category,
                    source=source,
                    context_question=context_question,
                )

            def wrapped_upsert_daily_metric(**kwargs) -> str:
                executed["upsert_daily_metric"] += 1
                return upsert_daily_metric(**kwargs)

            def wrapped_update_profile_attribute(**kwargs) -> str:
                executed["update_profile_attribute"] += 1
                return update_profile_attribute(**kwargs)

            tools = [METRICS_SKILL_SCHEMA, QUICK_DUMP_SKILL_SCHEMA, UPDATE_PROFILE_SKILL_SCHEMA]
            tool_map = {
                "upsert_daily_metric": wrapped_upsert_daily_metric,
                "save_reflection_record": wrapped_save_reflection_record,
                "update_profile_attribute": wrapped_update_profile_attribute,
            }

            chat_id = update.effective_chat.id
            history = self._history_by_chat.get(chat_id, [])
            messages = [{"role": "system", "content": system_prompt}, *history, {"role": "user", "content": user_prompt}]

            reply_text, _ = await self.llm.ask_with_tools_messages(messages, tools, tool_map)

            if sum(executed.values()) == 0:
                s = (user_text or "").strip()
                if reply_to_text and re.search(r"(修改|更新|改成|设为|设置|同步到|保存为|把.*改成|将.*改为)", s):
                    if re.search(r"(年度|yearly)", s, re.IGNORECASE):
                        yaml_path = "recent_focus.yearly_goal"
                    elif re.search(r"(季度|quarterly)", s, re.IGNORECASE):
                        yaml_path = "recent_focus.quarterly_goal"
                    elif re.search(r"(每月|月度|monthly)", s, re.IGNORECASE):
                        yaml_path = "recent_focus.monthly_goal"
                    elif re.search(r"(每周|周度|weekly)", s, re.IGNORECASE):
                        yaml_path = "recent_focus.weekly_goal"
                    else:
                        yaml_path = ""
                    if yaml_path:
                        m = re.search(r"(核心目标是|终极目标是|终极目标：|核心目标：)\s*(.+)", reply_to_text.strip())
                        inferred_value = (m.group(2).strip() if m else reply_to_text.strip())
                        result = wrapped_update_profile_attribute(
                            yaml_path=yaml_path,
                            new_value=inferred_value,
                            reason="用户希望将已确认的目标同步为长期周期目标，以便后续回顾与执行对齐。",
                            category="update",
                        )
                        if isinstance(result, str) and result.startswith("OK:"):
                            reply_text = "底层代码已重写：年度目标已对齐。"
                        else:
                            reply_text = result or "Error updating profile."
                if not reply_text and should_quick_dump(user_text, bool(reply_to_text)):
                    wrapped_save_reflection_record(
                        content=user_text,
                        category=categorize(user_text, bool(reply_to_text)),
                        source="Telegram",
                        context_question=reply_to_text or "",
                    )
                    reply_text = "已刻录"

            new_history = [*history, {"role": "user", "content": user_text}, {"role": "assistant", "content": reply_text or ""}]
            self._history_by_chat[chat_id] = new_history[-20:]

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
