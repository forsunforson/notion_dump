import json
import logging
import asyncio
import re
from app.services.telegram_service import TelegramService
from app.services.llm_service import LLMService
from app.jobs.periodic_review import PeriodicReviewJob
from app.utils.context_fetcher import ContextFetcher
from app.utils.text_chunking import split_text_smart

logger = logging.getLogger(__name__)


class DailyRoutines:
    def __init__(self):
        self.telegram = TelegramService()
        self.llm = LLMService()
        self.fetcher = ContextFetcher()
    
    async def morning_routine(self) -> bool:
        try:
            report_md = await PeriodicReviewJob(review_type="daily").run()
        except Exception as e:
            logger.error(f"Error generating daily review: {e}")
            report_md = ""

        if not report_md.strip():
            logger.error("Empty daily review content")
            return False

        try:
            ok = await self._send_long_message(report_md)
        except Exception as e:
            logger.error(f"Error sending daily review to Telegram: {e}")
            return False

        if not ok:
            return False

        await asyncio.sleep(1)

        try:
            plan_md = await self._generate_today_workout_plan()
        except Exception as e:
            logger.error(f"Error generating workout plan: {e}")
            plan_md = ""

        if not plan_md.strip():
            logger.error("Empty workout plan content")
            return False

        try:
            return await self._send_long_message(plan_md)
        except Exception as e:
            logger.error(f"Error sending workout plan to Telegram: {e}")
            return False
    
    async def weekly_review(self) -> bool:
        try:
            report_md = await PeriodicReviewJob(review_type="weekly").run()
        except Exception as e:
            logger.error(f"Error generating weekly review: {e}")
            return False

        if not report_md.strip():
            logger.error("Empty weekly review content")
            return False

        try:
            return await self._send_long_message(report_md)
        except Exception as e:
            logger.error(f"Error sending weekly review to Telegram: {e}")
            return False

    async def _generate_today_workout_plan(self) -> str:
        profile = self.fetcher.get_profile()
        user_name = profile.get("name", "ywy")
        physical_baseline = profile.get("physical_baseline", {})

        time_info = self.fetcher.get_time_info()
        current_date = time_info.get("current_date", "")
        current_weekday = time_info.get("current_weekday", "")

        weekly_routine = physical_baseline.get("weekly_routine", {})
        routine_desc = weekly_routine.get("description", "未设置")
        routine_pattern = weekly_routine.get("pattern", "未设置")
        primary_goals = physical_baseline.get("primary_goals", "") or "未设置"

        recent_metrics = self.fetcher.get_recent_metrics(3)
        recent_workout_logs = self.fetcher.get_recent_workout_logs(7)

        metrics_text = ""
        if recent_metrics:
            metrics_text = "\n\n".join([json.dumps(m, ensure_ascii=False, indent=2) for m in recent_metrics])
        else:
            metrics_text = "暂无近期身体状态数据。"

        system_prompt = f"""你是一个顶级的私人教练。用户的名字是 {user_name}。
你的任务是为用户提供【今日专属训练计划】。

【核心原则】
1. 动态调整：仔细阅读用户过去 7 天的真实训练记录。即使用户的基准目标是「{routine_desc}」，基准计划是「{routine_pattern}」，你也必须根据他最近的实际情况推断今天最合理的训练部位（推/拉/腿/恢复）。
2. 证据约束：绝对不要捏造用户没有做过的训练。训练历史缺失时，先给出“保守且通用”的方案（如动态恢复/低容量），并说明理由。
3. 简洁落地：输出必须清晰可执行，避免套话。

【输出要求（Markdown）】
- 标题：🏋️ 今日训练计划（含日期）
- 简要点评（1句话）：评价最近训练执行情况
- 今日重点（1句话）：明确今天练什么
- 计划列表：用 Markdown 列表列出动作与组数/次数/强度建议
- 结束：给出 1 条“最关键的注意点”（只允许 1 条）"""

        user_prompt = f"""当地时间：{current_date}，{current_weekday}
用户核心目标：{primary_goals}

【过去 7 天实际训练记录】
{recent_workout_logs}

【过去 3 天量化指标（参考）】
{metrics_text}

请输出今日训练计划。"""

        text = await self.llm.ask_text(system_prompt, user_prompt, max_tokens=800)
        return (text or "").strip()

    async def _send_long_message(self, text: str, max_chars: int = 3500) -> bool:
        parts = split_text_smart(text, max_chars=max_chars)
        for i, part in enumerate(parts):
            ok = await self.telegram.send_message(part)
            if not ok:
                return False
            if i < len(parts) - 1:
                await asyncio.sleep(1)
        return True
