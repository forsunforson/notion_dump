import os
import json
import logging
import datetime
import re
from pathlib import Path
from zoneinfo import ZoneInfo
import yaml

logger = logging.getLogger(__name__)


class ContextFetcher:
    DAILY_ENTRY_TITLE = "Daily Entry"

    def __init__(self):
        self.project_root = Path(os.getcwd())
        self.profile_file = self.project_root / "config" / "profile.yaml"
        self.metrics_file = self.project_root / "notion_output" / "metrics.jsonl"
        self.reports_dir = self.project_root / "_reports"
        self.notion_output_dir = self.project_root / "notion_output"
        self.history_file = self.project_root / "notion-dump-history.jsonl"

    @staticmethod
    def parse_frontmatter(content: str) -> dict:
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if not match:
            return {}
        try:
            data = yaml.safe_load(match.group(1)) or {}
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    @classmethod
    def is_daily_entry(cls, content: str) -> bool:
        metadata = cls.parse_frontmatter(content)
        title = metadata.get("title", "")
        return isinstance(title, str) and title == cls.DAILY_ENTRY_TITLE
    
    def get_profile(self) -> dict:
        if not self.profile_file.exists():
            logger.warning(f"Profile file not found: {self.profile_file}")
            return {}
        
        try:
            with open(self.profile_file, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Error reading profile file: {e}")
            return {}
    
    def get_time_info(self, timezone_str: str) -> dict:
        try:
            tz = ZoneInfo(timezone_str)
        except Exception:
            tz = ZoneInfo("Asia/Shanghai")
        
        now = datetime.datetime.now(tz)
        weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        
        return {
            "current_date": now.strftime("%Y-%m-%d"),
            "current_weekday": weekday_names[now.weekday()]
        }
    
    def extract_date_from_yaml(self, content: str) -> str | None:
        try:
            profile = self.get_profile()
            preferences = profile.get("preferences", {})
            timezone_str = preferences.get("timezone", "Asia/Shanghai")
            tz = ZoneInfo(timezone_str)
        except Exception:
            tz = ZoneInfo("Asia/Shanghai")
        
        yaml_match = re.search(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        if not yaml_match:
            return None
        
        yaml_content = yaml_match.group(1)
        created_match = re.search(r'created_time:\s*["\']?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z?["\']?', yaml_content)
        
        if not created_match:
            return None
        
        utc_time_str = created_match.group(1)
        try:
            utc_time = datetime.datetime.strptime(utc_time_str, "%Y-%m-%dT%H:%M:%S")
            utc_time = utc_time.replace(tzinfo=datetime.timezone.utc)
            local_time = utc_time.astimezone(tz)
            return local_time.strftime("%Y-%m-%d")
        except ValueError:
            return None
    
    def get_recent_metrics(self, count: int = 3) -> list:
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
    
    def get_latest_report(self) -> str:
        if not self.reports_dir.exists():
            return ""
        
        report_files = sorted(self.reports_dir.glob("report_*.md"), reverse=True)
        if not report_files:
            return ""
        
        try:
            with open(report_files[0], "r", encoding="utf-8") as f:
                content = f.read(4000)
                return self.localize_text_timestamps(content)
        except Exception as e:
            logger.error(f"Error reading report {report_files[0]}: {e}")
            return ""
    
    def get_reports_from_last_n_days(self, days: int = 7) -> str:
        if not self.reports_dir.exists():
            return ""
        
        profile = self.get_profile()
        preferences = profile.get("preferences", {})
        timezone_str = preferences.get("timezone", "Asia/Shanghai")
        
        try:
            tz = ZoneInfo(timezone_str)
        except Exception:
            tz = ZoneInfo("Asia/Shanghai")
        
        cutoff_date = datetime.datetime.now(tz) - datetime.timedelta(days=days)
        cutoff_str = cutoff_date.strftime("%Y-%m-%d")
        
        report_files = sorted(self.reports_dir.glob("report_*.md"), reverse=True)
        valid_reports = []
        
        for report_file in report_files:
            date_str = report_file.stem.replace("report_", "")
            if date_str >= cutoff_str:
                try:
                    with open(report_file, "r", encoding="utf-8") as f:
                        content = f.read(2000)
                        content = self.localize_text_timestamps(content)
                        valid_reports.append(f"=== {date_str} ===\n{content}")
                except Exception as e:
                    logger.error(f"Error reading report {report_file}: {e}")
        
        return "\n\n".join(valid_reports) if valid_reports else ""
    
    def get_recent_workout_logs(self, days: int = 7) -> str:
        profile = self.get_profile()
        preferences = profile.get("preferences", {})
        timezone_str = preferences.get("timezone", "Asia/Shanghai")
        
        try:
            tz = ZoneInfo(timezone_str)
        except Exception:
            tz = ZoneInfo("Asia/Shanghai")
        
        cutoff_date = datetime.datetime.now(tz) - datetime.timedelta(days=days)
        cutoff_str = cutoff_date.strftime("%Y-%m-%d")
        
        workout_logs = []
        
        if self.notion_output_dir.exists():
            md_files = list(self.notion_output_dir.glob("*.md"))
            md_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            
            for md_file in md_files[:50]:
                try:
                    with open(md_file, "r", encoding="utf-8") as f:
                        raw_content = f.read(5000)
                except Exception as e:
                    logger.error(f"Error reading file {md_file}: {e}")
                    continue
                
                date_str = None
                
                yaml_match = re.search(r'^---\s*\n(.*?)\n---', raw_content, re.DOTALL)
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
                
                workout_match = re.search(r'###\s*🏋️\s*Workout\s*\n(.*?)(?=\n###|\n##|\n---|\Z)', raw_content, re.DOTALL | re.IGNORECASE)
                
                if not workout_match:
                    workout_match = re.search(r'###\s*Workout\s*\n(.*?)(?=\n###|\n##|\n---|\Z)', raw_content, re.DOTALL | re.IGNORECASE)
                
                if not workout_match:
                    workout_match = re.search(r'##\s*🏋️\s*Workout\s*\n(.*?)(?=\n###|\n##|\n---|\Z)', raw_content, re.DOTALL | re.IGNORECASE)
                
                if not workout_match:
                    workout_match = re.search(r'##\s*Workout\s*\n(.*?)(?=\n###|\n##|\n---|\Z)', raw_content, re.DOTALL | re.IGNORECASE)
                
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
    
    def get_history_from_last_n_days(self, days: int = 7) -> str:
        if not self.history_file.exists():
            return ""
        
        profile = self.get_profile()
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
    
    def localize_text_timestamps(self, text: str) -> str:
        profile = self.get_profile()
        preferences = profile.get("preferences", {})
        timezone_str = preferences.get("timezone", "Asia/Shanghai")
        
        try:
            tz = ZoneInfo(timezone_str)
        except Exception:
            tz = ZoneInfo("Asia/Shanghai")
        
        pattern = r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?'
        
        def repl(match):
            try:
                timestamp_str = match.group(0)
                dt = datetime.datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                local_dt = dt.astimezone(tz)
                return local_dt.strftime("%Y-%m-%d %H:%M:%S") + " (当地时间)"
            except Exception:
                return match.group(0)
        
        return re.sub(pattern, repl, text)
