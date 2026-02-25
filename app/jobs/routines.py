import os
import json
import logging
import datetime
import asyncio
from pathlib import Path
from zoneinfo import ZoneInfo
import yaml
from openai import AsyncOpenAI
from app.services.telegram_service import TelegramService

logger = logging.getLogger(__name__)


class DailyRoutines:
    def __init__(self):
        self.api_key = os.getenv("AI_API_KEY")
        self.base_url = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
        self.model = os.getenv("AI_MODEL", "gpt-3.5-turbo")
        
        if not self.api_key:
            raise ValueError("AI_API_KEY not set")
        
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        self.telegram = TelegramService()
        self.project_root = Path(os.getcwd())
        self.reports_dir = self.project_root / "_reports"
        self.history_file = self.project_root / "notion-dump-history.jsonl"
        self.profile_file = self.project_root / "config" / "profile.yaml"
        self.metrics_file = self.project_root / "notion_output" / "metrics.jsonl"
    
    def _load_profile(self) -> dict:
        if not self.profile_file.exists():
            logger.warning(f"Profile file not found: {self.profile_file}")
            return {}
        
        try:
            with open(self.profile_file, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Error reading profile file: {e}")
            return {}
    
    def _get_recent_metrics(self, count: int = 3) -> list:
        if not self.metrics_file.exists():
            logger.warning(f"Metrics file not found: {self.metrics_file}")
            return []
        
        try:
            lines = []
            with open(self.metrics_file, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
                lines = all_lines[-count:] if len(all_lines) >= count else all_lines
            
            metrics = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    metrics.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            
            return metrics
        except Exception as e:
            logger.error(f"Error reading metrics file: {e}")
            return []
    
    def _get_latest_report(self) -> str:
        if not self.reports_dir.exists():
            return ""
        
        report_files = sorted(self.reports_dir.glob("report_*.md"), reverse=True)
        if not report_files:
            return ""
        
        try:
            with open(report_files[0], "r", encoding="utf-8") as f:
                return f.read(4000)
        except Exception as e:
            logger.error(f"Error reading report {report_files[0]}: {e}")
            return ""
    
    def _get_reports_from_last_n_days(self, days: int = 7) -> str:
        if not self.reports_dir.exists():
            return ""
        
        cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days)
        cutoff_str = cutoff_date.strftime("%Y-%m-%d")
        
        report_files = sorted(self.reports_dir.glob("report_*.md"), reverse=True)
        valid_reports = []
        
        for report_file in report_files:
            date_str = report_file.stem.replace("report_", "")
            if date_str >= cutoff_str:
                try:
                    with open(report_file, "r", encoding="utf-8") as f:
                        content = f.read(2000)
                        valid_reports.append(f"=== {date_str} ===\n{content}")
                except Exception as e:
                    logger.error(f"Error reading report {report_file}: {e}")
        
        return "\n\n".join(valid_reports) if valid_reports else ""
    
    def _get_history_from_last_n_days(self, days: int = 7) -> str:
        if not self.history_file.exists():
            return ""
        
        profile = self._load_profile()
        preferences = profile.get("preferences", {})
        timezone_str = preferences.get("timezone", "Asia/Shanghai")
        
        try:
            tz = ZoneInfo(timezone_str)
        except Exception:
            logger.error(f"Invalid timezone in profile: {timezone_str}")
            return ""
        
        cutoff_date = datetime.datetime.now(tz) - datetime.timedelta(days=days)
        cutoff_str = cutoff_date.strftime('%Y-%m-%dT%H:%M:%S')
        
        entries = []
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        timestamp = entry.get("timestamp", "")
                        if timestamp >= cutoff_str:
                            entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Error reading history file: {e}")
            return ""
        
        if not entries:
            return ""
        
        summary_parts = []
        for entry in entries[-10:]:
            timestamp = entry.get("timestamp", "Unknown")
            stats = entry.get("stats", {})
            details = entry.get("details", [])
            
            summary_parts.append(f"- {timestamp}: Created {stats.get('created_count', 0)}, Updated {stats.get('updated_count', 0)}")
            for detail in details[:3]:
                summary_parts.append(f"  - {detail.get('title', 'Untitled')} ({detail.get('action', 'Unknown')})")
        
        return "\n".join(summary_parts)
    
    async def morning_routine(self) -> bool:
        logger.info("Starting morning routine (dual-track mode)...")
        
        profile = self._load_profile()
        user_name = profile.get('name', 'ywy')
        preferences = profile.get("preferences", {})
        physical_baseline = profile.get("physical_baseline", {})
        
        timezone_str = preferences.get("timezone", "Asia/Shanghai")
        try:
            tz = ZoneInfo(timezone_str)
        except Exception:
            tz = ZoneInfo("Asia/Shanghai")
        
        now = datetime.datetime.now(tz)
        weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        current_date = now.strftime("%Y-%m-%d")
        current_weekday = weekday_names[now.weekday()]
        date_info = f"当地时间：{current_date}，{current_weekday}"
        
        weekly_routine = physical_baseline.get("weekly_routine", {})
        primary_goals = physical_baseline.get("primary_goals", "")
        
        latest_report = self._get_latest_report()
        recent_metrics = self._get_recent_metrics(3)
        
        message_a = ""
        try:
            system_prompt_a = f"你是一个贴心的私人助理。用户的名字是 {user_name}。现在是早上。请根据用户最近的知识库报告生成晨间问候。用友好的口吻总结昨夜的知识沉淀或重要待办，语气轻松，控制在 300 字以内。打招呼时直接使用「{user_name}」这个名字，绝对不要输出 [User Name] 这种占位符。"
            
            if latest_report:
                user_prompt_a = f"请根据以下知识库报告生成晨间问候：\n\n<report>\n{latest_report}\n</report>"
            else:
                user_prompt_a = "暂无新的知识库报告，请生成一条轻松的晨间问候。"
            
            response_a = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt_a},
                    {"role": "user", "content": user_prompt_a}
                ],
                max_tokens=500,
                stream=False
            )
            message_a = response_a.choices[0].message.content
            logger.info(f"Generated knowledge brief: {message_a[:100]}...")
        except Exception as e:
            logger.error(f"Error generating knowledge brief: {e}")
            message_a = "早安！知识简报生成失败，请稍后查看。"
        
        message_b = ""
        try:
            system_prompt_b = f"你是一个专业的私人教练。用户的名字是 {user_name}。请根据用户的长期训练目标、预设的每周规律、今天是星期几，以及用户过去 3 天的量化状态数据，生成今日的专属训练建议。要求：1. 简要评价昨日的训练和恢复状态；2. 给出今日明确的训练重点或休息建议；3. 控制在 300 字以内，专业且有活力。打招呼时直接使用「{user_name}」这个名字，绝对不要输出 [User Name] 这种占位符。"
            
            routine_desc = weekly_routine.get("description", "未设置")
            routine_pattern = weekly_routine.get("pattern", "未设置")
            
            metrics_text = ""
            if recent_metrics:
                metrics_lines = []
                for m in recent_metrics:
                    metrics_lines.append(json.dumps(m, ensure_ascii=False, indent=2))
                metrics_text = "\n\n".join(metrics_lines)
            else:
                metrics_text = "暂无近期身体状态数据。"
            
            user_prompt_b = f"""请根据以下信息生成今日训练建议：

{date_info}

【训练目标】
{primary_goals if primary_goals else "未设置"}

【每周规律】
- 描述：{routine_desc}
- 模式：{routine_pattern}

【最近 3 天身体状态】
{metrics_text}
"""
            
            response_b = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt_b},
                    {"role": "user", "content": user_prompt_b}
                ],
                max_tokens=500,
                stream=False
            )
            message_b = response_b.choices[0].message.content
            logger.info(f"Generated training plan: {message_b[:100]}...")
        except Exception as e:
            logger.error(f"Error generating training plan: {e}")
            message_b = "今日训练建议生成失败，请稍后查看。"
        
        try:
            success_a = await self.telegram.send_message(message_a)
            if not success_a:
                logger.error("Failed to send knowledge brief")
                return False
            
            await asyncio.sleep(1)
            
            success_b = await self.telegram.send_message(message_b)
            if not success_b:
                logger.error("Failed to send training plan")
                return False
            
            logger.info("Morning routine (dual-track) completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error in morning routine message delivery: {e}")
            return False
    
    async def weekly_review(self) -> bool:
        logger.info("Starting weekly review...")
        
        reports_content = self._get_reports_from_last_n_days(7)
        history_content = self._get_history_from_last_n_days(7)
        
        context_parts = []
        if reports_content:
            context_parts.append(f"<weekly_reports>\n{reports_content}\n</weekly_reports>")
        if history_content:
            context_parts.append(f"<activity_log>\n{history_content}\n</activity_log>")
        
        context = "\n\n".join(context_parts) if context_parts else "暂无本周的活动数据。"
        
        system_prompt = """你是一个知识管理助手。请根据用户过去一周的知识库变动，生成一份"本周知识回顾"。

输出要求：
1. 使用 Markdown 格式
2. 包含以下部分：
   - 本周概览（总体变化统计）
   - 重点内容回顾（最重要的 3-5 个主题）
   - 待办事项提醒（如果有未完成的任务）
   - 下周建议
3. 控制在 800 字以内
4. 语气专业但友好"""
        
        user_prompt = f"请根据以下本周数据生成本周知识回顾：\n\n{context}"
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=1200,
                stream=False
            )
            
            message = response.choices[0].message.content
            logger.info(f"Generated weekly review: {message[:100]}...")
            
            success = await self.telegram.send_message(message)
            if success:
                logger.info("Weekly review completed successfully")
            else:
                logger.warning("Weekly review completed but message delivery failed")
            
            return success
            
        except Exception as e:
            logger.error(f"Error in weekly review: {e}")
            return False
