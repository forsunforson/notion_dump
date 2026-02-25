import os
import json
import logging
import datetime
import asyncio
import re
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
    
    def _get_recent_workout_logs(self, days: int = 7) -> str:
        profile = self._load_profile()
        preferences = profile.get("preferences", {})
        timezone_str = preferences.get("timezone", "Asia/Shanghai")
        
        try:
            tz = ZoneInfo(timezone_str)
        except Exception:
            tz = ZoneInfo("Asia/Shanghai")
        
        cutoff_date = datetime.datetime.now(tz) - datetime.timedelta(days=days)
        cutoff_str = cutoff_date.strftime("%Y-%m-%d")
        
        workout_logs = []
        
        notion_output_dir = self.project_root / "notion_output"
        if notion_output_dir.exists():
            md_files = list(notion_output_dir.glob("*.md"))
            md_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            
            for md_file in md_files[:50]:
                try:
                    with open(md_file, "r", encoding="utf-8") as f:
                        content = f.read(5000)
                except Exception as e:
                    logger.error(f"Error reading file {md_file}: {e}")
                    continue
                
                date_str = None
                
                yaml_match = re.search(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
                if yaml_match:
                    yaml_content = yaml_match.group(1)
                    created_match = re.search(r'created_time:\s*["\']?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z?["\']?', yaml_content)
                    if created_match:
                        utc_time_str = created_match.group(1)
                        try:
                            utc_time = datetime.datetime.strptime(utc_time_str, "%Y-%m-%dT%H:%M:%S")
                            utc_time = utc_time.replace(tzinfo=datetime.timezone.utc)
                            local_time = utc_time.astimezone(tz)
                            date_str = local_time.strftime("%Y-%m-%d")
                        except ValueError:
                            date_str = created_match.group(1)[:10]
                
                if not date_str or date_str < cutoff_str:
                    continue
                
                workout_match = re.search(r'###\s*🏋️\s*Workout\s*\n(.*?)(?=\n###|\n##|\n---|\Z)', content, re.DOTALL | re.IGNORECASE)
                
                if not workout_match:
                    workout_match = re.search(r'###\s*Workout\s*\n(.*?)(?=\n###|\n##|\n---|\Z)', content, re.DOTALL | re.IGNORECASE)
                
                if not workout_match:
                    workout_match = re.search(r'##\s*🏋️\s*Workout\s*\n(.*?)(?=\n###|\n##|\n---|\Z)', content, re.DOTALL | re.IGNORECASE)
                
                if not workout_match:
                    workout_match = re.search(r'##\s*Workout\s*\n(.*?)(?=\n###|\n##|\n---|\Z)', content, re.DOTALL | re.IGNORECASE)
                
                if workout_match:
                    workout_content = workout_match.group(1).strip()
                    lines = workout_content.split('\n')
                    meaningful_lines = [l.strip() for l in lines if l.strip() and not l.strip().startswith('>')]
                    
                    if meaningful_lines:
                        workout_summary = '\n'.join(meaningful_lines[:15])
                        workout_logs.append(f"[{date_str}]:\n{workout_summary}")
        
        if not workout_logs and self.reports_dir.exists():
            report_files = sorted(self.reports_dir.glob("report_*.md"), reverse=True)
            
            for report_file in report_files:
                date_str = report_file.stem.replace("report_", "")
                if date_str < cutoff_str:
                    continue
                
                try:
                    with open(report_file, "r", encoding="utf-8") as f:
                        content = f.read()
                    
                    workout_patterns = [
                        r'\*\*Workout\*\*[:：]?\s*([^\n]+(?:\n(?!\*\*)[^\n]+)*)',
                        r'- \*\*Workout\*\*[:：]?\s*([^\n]+)',
                        r'Workout[:：]\s*([^\n]+)',
                    ]
                    
                    found_workout = False
                    for pattern in workout_patterns:
                        matches = re.findall(pattern, content, re.IGNORECASE)
                        if matches:
                            for match in matches:
                                workout_text = match.strip()
                                if workout_text:
                                    workout_logs.append(f"[{date_str}]: {workout_text}")
                                    found_workout = True
                    
                    if not found_workout:
                        insights_pattern = r'- \*\*Workout\*\*[:：]?\s*([^\n]+)'
                        insights_matches = re.findall(insights_pattern, content, re.IGNORECASE)
                        
                        for match in insights_matches:
                            workout_text = match.strip()
                            if workout_text:
                                workout_logs.append(f"[{date_str}]: {workout_text}")
                                found_workout = True
                            
                except Exception as e:
                    logger.error(f"Error reading report {report_file}: {e}")
        
        if not workout_logs and self.metrics_file.exists():
            try:
                recent_metrics = []
                with open(self.metrics_file, "r", encoding="utf-8") as f:
                    all_lines = f.readlines()
                    recent_metrics = all_lines[-days:] if len(all_lines) >= days else all_lines
                
                for line in recent_metrics:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        metric = json.loads(line)
                        date_str = metric.get("date", "")
                        workout_score = metric.get("workout_volume_score")
                        
                        if date_str and workout_score is not None:
                            energy = metric.get("energy_level", "N/A")
                            workout_logs.append(f"[{date_str}]: 训练强度评分 {workout_score}/10, 精力水平 {energy}")
                    except json.JSONDecodeError:
                        continue
            except Exception as e:
                logger.error(f"Error reading metrics file: {e}")
        
        if not workout_logs:
            return "过去 7 天无明确训练记录"
        
        return "\n\n".join(workout_logs)
    
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
        recent_workout_logs = self._get_recent_workout_logs(7)
        
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
            routine_desc = weekly_routine.get("description", "未设置")
            routine_pattern = weekly_routine.get("pattern", "未设置")
            
            system_prompt_b = f"""你是一个顶级的私人教练。用户的名字是 {user_name}。
你的任务是为用户提供【今日专属训练计划】。

【核心原则】
1. 动态调整：仔细阅读用户过去 7 天的真实训练记录。即使用户的基准计划是「{routine_desc}」，你也必须根据他昨天/前天的实际情况（比如是否休息了、是否跳过了某练）来推断今天最合理的训练部位。
2. 格式匹配：输出格式必须与用户的日常记录格式高度匹配，直接给出清晰的动作列表。

【输出要求】
- 简要点评（1句话）：评价最近的训练执行情况。
- 今日重点（1句话）：明确今天是练什么（如：推/拉/腿/动态恢复）。
- 计划列表：用 Markdown 列表清晰列出推荐的训练动作及组数/重量/次数建议（如：格式参考用户过去的训练记录）。
- 避免废话：不要输出"加油"、"注意安全"等套话。绝对不要捏造用户没有做过的训练。"""
            
            metrics_text = ""
            if recent_metrics:
                metrics_lines = []
                for m in recent_metrics:
                    metrics_lines.append(json.dumps(m, ensure_ascii=False, indent=2))
                metrics_text = "\n\n".join(metrics_lines)
            else:
                metrics_text = "暂无近期身体状态数据。"
            
            user_prompt_b = f"""当地时间：{current_date}，{current_weekday}
用户的核心目标：{primary_goals if primary_goals else "未设置"}

【过去 7 天实际训练记录】
{recent_workout_logs}

【过去 3 天量化指标 (参考)】
{metrics_text}

请根据以上真实记录，生成今日的训练计划。"""
            
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


def test_get_recent_workout_logs():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    file_dir = Path(__file__).resolve().parent
    project_root = file_dir.parent.parent
    
    original_cwd = os.getcwd()
    os.chdir(project_root)
    
    try:
        os.environ.pop("AI_API_KEY", None)
        
        class TestDailyRoutines:
            def __init__(self):
                self.project_root = Path(os.getcwd())
                self.reports_dir = self.project_root / "_reports"
                self.history_file = self.project_root / "notion-dump-history.jsonl"
                self.profile_file = self.project_root / "config" / "profile.yaml"
                self.metrics_file = self.project_root / "notion_output" / "metrics.jsonl"
            
            def _load_profile(self) -> dict:
                if not self.profile_file.exists():
                    return {}
                try:
                    with open(self.profile_file, "r", encoding="utf-8") as f:
                        return yaml.safe_load(f) or {}
                except Exception:
                    return {}
        
        test_obj = TestDailyRoutines()
        
        routines = DailyRoutines.__new__(DailyRoutines)
        routines.project_root = test_obj.project_root
        routines.reports_dir = test_obj.reports_dir
        routines.history_file = test_obj.history_file
        routines.profile_file = test_obj.profile_file
        routines.metrics_file = test_obj.metrics_file
        routines._load_profile = test_obj._load_profile
        
        result = routines._get_recent_workout_logs(days=7)
        
        print("\n" + "="*60)
        print("【最近 7 天训练记录测试结果】")
        print("="*60)
        print(result)
        print("="*60)
        
    finally:
        os.chdir(original_cwd)


if __name__ == "__main__":
    test_get_recent_workout_logs()
