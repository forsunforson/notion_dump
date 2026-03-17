import json
import logging
import asyncio
import re
from app.services.telegram_service import TelegramService
from app.services.llm_service import LLMService
from app.services.prompt_manager import PromptManager
from app.jobs.periodic_review import PeriodicReviewJob
from app.services.context_fetcher import ContextFetcher
from app.utils.text_chunking import split_text_smart

logger = logging.getLogger(__name__)


class DailyRoutines:
    def __init__(self):
        self.telegram = TelegramService()
        self.llm = LLMService()
        self.fetcher = ContextFetcher()
        self.prompt_manager = PromptManager()
    
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
        fitness_plan = profile.get("fitness_plan", {})
        physical_baseline = profile.get("physical_baseline", {})

        time_info = self.fetcher.get_time_info()
        current_date = time_info.get("current_date", "")
        current_weekday = time_info.get("current_weekday", "")
        
        weekly_routine = fitness_plan.get("weekly_cycle", {})
        routine_desc = fitness_plan.get("recent_focus", "") or "未设置"
        primary_goals = physical_baseline.get("primary_goals", "") or "未设置"

        recent_metrics = self.fetcher.get_recent_metrics(3)
        recent_workout_logs = self.fetcher.get_recent_workout_logs(7)

        metrics_text = ""
        if recent_metrics:
            metrics_text = "\n\n".join([json.dumps(m, ensure_ascii=False, indent=2) for m in recent_metrics])
        else:
            metrics_text = "暂无近期身体状态数据。"

        system_prompt, user_prompt = self.prompt_manager.build_workout_plan_prompts(
            user_name=user_name,
            routine_desc=routine_desc,
            routine_pattern=str(weekly_routine),
            current_date=current_date,
            current_weekday=current_weekday,
            primary_goals=primary_goals,
            recent_workout_logs=recent_workout_logs,
            metrics_text=metrics_text,
        )

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
