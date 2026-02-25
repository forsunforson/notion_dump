import os
import json
import logging
import datetime
from pathlib import Path
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
        
        cutoff_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
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
        logger.info("Starting morning routine...")
        
        latest_report = self._get_latest_report()
        context = ""
        
        if latest_report:
            context = f"<recent_report>\n{latest_report}\n</recent_report>"
        else:
            context = "暂无最近的报告数据。"
        
        system_prompt = """你是一个贴心的私人助理。现在是早上。请根据用户最近的知识库变动和训练计划，生成一份简短、充满活力的晨间问候。内容需包含：今日训练重点、昨夜可能关心的知识话题。请用友好的口吻输出，适合在 Telegram 上阅读。

输出要求：
1. 使用 Markdown 格式
2. 控制在 500 字以内
3. 语气轻松友好
4. 如果有具体的待办事项，用列表形式展示"""
        
        user_prompt = f"请根据以下最近的报告内容生成晨间问候：\n\n{context}"
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=800,
                stream=False
            )
            
            message = response.choices[0].message.content
            logger.info(f"Generated morning message: {message[:100]}...")
            
            success = await self.telegram.send_message(message)
            if success:
                logger.info("Morning routine completed successfully")
            else:
                logger.warning("Morning routine completed but message delivery failed")
            
            return success
            
        except Exception as e:
            logger.error(f"Error in morning routine: {e}")
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
