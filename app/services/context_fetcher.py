import os
import json
import logging
import datetime
import re
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Callable
import yaml

from app.core.paths import project_root, config_dir, output_dir, reports_dir
from app.utils.frontmatter import parse_frontmatter, parse_frontmatter_meta
from app.utils.timezone_utils import load_profile_timezone

logger = logging.getLogger(__name__)


class ContextFetcher:
    DAILY_ENTRY_TITLE = "Daily Entry"
    DIARY_TAGS = {"Diary", "日记"}
    DIARY_TYPE_FIELD = "type"
    DIARY_TYPE_VALUES = {"diary", "Diary", "日记"}
    TRADE_LOG_MARKER = "Trade Snapshot Log"
    TRADE_ACTION_VALUES = {"BUY", "SELL"}

    def __init__(self):
        self.project_root = project_root()
        self.profile_file = Path(os.getenv("PROFILE_YAML_PATH") or (config_dir() / "profile.yaml"))
        self.metrics_file = output_dir() / "metrics.jsonl"
        self.reports_dir = reports_dir()
        self.notion_output_dir = output_dir()
        self.history_file = self.project_root / "chronofold-history.jsonl"
        self.legacy_history_file = self.project_root / "notion-dump-history.jsonl"
        self.history_files = [self.history_file, self.legacy_history_file]

    @staticmethod
    def parse_frontmatter(content: str) -> dict:
        return parse_frontmatter_meta(content)

    @classmethod
    def is_daily_entry(cls, content: str) -> bool:
        metadata = cls.parse_frontmatter(content)
        if not metadata:
            return False

        type_value = metadata.get(cls.DIARY_TYPE_FIELD)
        if isinstance(type_value, str) and type_value.strip() in cls.DIARY_TYPE_VALUES:
            return True

        tags_value = metadata.get("tags")
        if isinstance(tags_value, list):
            for t in tags_value:
                if isinstance(t, str) and t.strip() in cls.DIARY_TAGS:
                    return True

        title = metadata.get("title", "")
        return isinstance(title, str) and title.strip() == cls.DAILY_ENTRY_TITLE

    @classmethod
    def is_trade_log_entry(cls, content: str) -> bool:
        if not content:
            return False
        metadata = cls.parse_frontmatter(content)
        if not metadata:
            return False
        v = metadata.get("action")
        if v is None:
            v = metadata.get("Action")
        if not isinstance(v, str) or not v.strip():
            return False
        return v.strip().upper() in cls.TRADE_ACTION_VALUES

    def collect_markdown_by_filters(
        self,
        *,
        filters: dict[str, Callable[[str], bool]],
    ) -> tuple[int, dict[str, list[dict]]]:
        if not self.notion_output_dir.exists():
            return 0, {k: [] for k in filters.keys()}

        md_files = list(self.notion_output_dir.glob("**/*.md"))
        buckets: dict[str, list[dict]] = {k: [] for k in filters.keys()}

        for md_file in md_files:
            try:
                raw = md_file.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to read file {md_file}: {e}")
                continue

            for name, fn in filters.items():
                try:
                    ok = fn(raw)
                except Exception as e:
                    logger.warning(f"Filter {name} failed for file {md_file}: {e}")
                    continue
                if ok:
                    buckets[name].append({"path": str(md_file), "raw": raw})

        return len(md_files), buckets

    def make_daily_entry_filter(
        self, *, start_utc: datetime.datetime, end_utc: datetime.datetime
    ) -> Callable[[str], bool]:
        def _f(raw: str) -> bool:
            if not self.is_daily_entry(raw):
                return False
            meta = self.parse_frontmatter(raw)
            if not meta:
                return False
            created_utc = self._parse_created_time_utc(meta)
            if not created_utc:
                return False
            return start_utc <= created_utc < end_utc

        return _f

    def make_trade_log_filter(
        self, *, start_utc: datetime.datetime, end_utc: datetime.datetime
    ) -> Callable[[str], bool]:
        def _f(raw: str) -> bool:
            if not self.is_trade_log_entry(raw):
                return False
            meta = self.parse_frontmatter(raw)
            if not meta:
                return False
            created_utc = self._parse_created_time_utc(meta)
            if not created_utc:
                return False
            return start_utc <= created_utc < end_utc

        return _f

    def make_book_review_filter(
        self, *, start_utc: datetime.datetime, end_utc: datetime.datetime
    ) -> Callable[[str], bool]:
        def _f(raw: str) -> bool:
            meta = self.parse_frontmatter(raw)
            if not meta:
                return False
            t = meta.get("type")
            if not (isinstance(t, str) and t.strip() == "book_review"):
                return False
            created_utc = self._parse_created_time_utc(meta)
            if not created_utc:
                return False
            return start_utc <= created_utc < end_utc

        return _f

    def make_movie_review_filter(
        self, *, start_utc: datetime.datetime, end_utc: datetime.datetime
    ) -> Callable[[str], bool]:
        def _f(raw: str) -> bool:
            meta = self.parse_frontmatter(raw)
            if not meta:
                return False
            t = meta.get("type")
            if not (isinstance(t, str) and t.strip() == "movie_review"):
                return False
            created_utc = self._parse_created_time_utc(meta)
            if not created_utc:
                return False
            return start_utc <= created_utc < end_utc

        return _f

    def make_chatlog_filter(
        self, *, start_utc: datetime.datetime, end_utc: datetime.datetime
    ) -> Callable[[str], bool]:
        def _f(raw: str) -> bool:
            meta = self.parse_frontmatter(raw)
            if not meta:
                return False
            v = meta.get("category")
            ok = False
            if isinstance(v, str):
                ok = v.strip() == "chatlog"
            elif isinstance(v, list):
                ok = any(isinstance(x, str) and x.strip() == "chatlog" for x in v)
            if not ok:
                return False
            created_utc = self._parse_created_time_utc(meta)
            if not created_utc:
                return False
            return start_utc <= created_utc < end_utc

        return _f

    def build_entry(
        self,
        *,
        raw: str,
        path: str | Path,
        tz: ZoneInfo | None = None,
        include_path: bool = False,
    ) -> dict | None:
        tz = tz or load_profile_timezone()
        frontmatter, body = parse_frontmatter(raw or "")
        if not frontmatter:
            return None
        created_utc = self._parse_created_time_utc(frontmatter)
        if not created_utc:
            return None
        title = self._get_title(frontmatter, Path(path))
        local_date = created_utc.astimezone(tz).date().isoformat()
        cleaned_body = self._clean_body(body, title)
        entry: dict = {
            "created_utc": created_utc,
            "local_date": local_date,
            "title": title,
            "body": cleaned_body,
        }
        if include_path:
            entry["path"] = str(path)
        return entry

    @staticmethod
    def _parse_created_time_utc(frontmatter: dict) -> datetime.datetime | None:
        value = frontmatter.get("created_time")
        if not value:
            return None
        if isinstance(value, datetime.datetime):
            dt = value
        elif isinstance(value, str):
            s = value.strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            try:
                dt = datetime.datetime.fromisoformat(s)
            except ValueError:
                return None
        else:
            return None

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)

    @staticmethod
    def _get_title(frontmatter: dict, md_file: Path) -> str:
        title = frontmatter.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        return md_file.stem

    @staticmethod
    def _clean_body(body: str, title: str) -> str:
        if not body:
            return ""
        stripped = body.lstrip()
        if stripped.startswith("# "):
            first_line = stripped.splitlines()[0][2:].strip()
            if first_line == title:
                stripped = "\n".join(stripped.splitlines()[1:]).lstrip("\n")
        return stripped.strip()

    def get_profile(self) -> dict:
        if not self.profile_file.exists():
            logger.warning(f"Profile file not found: {self.profile_file}")
            return {}

        try:
            with open(self.profile_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                logger.error("Profile file root is not a mapping")
                return {}
            custom_traits = data.get("custom_traits")
            if custom_traits is None:
                data["custom_traits"] = {}
            elif not isinstance(custom_traits, dict):
                data["custom_traits"] = {}
            return data
        except Exception as e:
            logger.error(f"Error reading profile file: {e}")
            return {}

    def get_time_info(self) -> dict:
        tz = load_profile_timezone()

        now = datetime.datetime.now(tz)
        weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

        return {
            "current_date": now.strftime("%Y-%m-%d"),
            "current_weekday": weekday_names[now.weekday()],
        }

    def extract_date_from_yaml(self, content: str) -> str | None:
        tz = load_profile_timezone()

        yaml_match = re.search(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not yaml_match:
            return None

        yaml_content = yaml_match.group(1)
        created_match = re.search(
            r'created_time:\s*["\']?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z?["\']?',
            yaml_content,
        )

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

        report_files = sorted(
            self.reports_dir.glob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not report_files:
            return ""

        report_file = report_files[0]
        try:
            with open(report_file, "r", encoding="utf-8") as f:
                content = f.read(6000)
                return self.localize_text_timestamps(content)
        except Exception as e:
            logger.error(f"Error reading report {report_file}: {e}")
            return ""

    def get_reports_from_last_n_days(self, days: int = 7) -> str:
        if not self.reports_dir.exists():
            return ""

        tz = load_profile_timezone()

        cutoff_date = datetime.datetime.now(tz) - datetime.timedelta(days=days)
        cutoff_str = cutoff_date.strftime("%Y-%m-%d")

        report_files = sorted(
            self.reports_dir.glob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        valid_reports = []

        for report_file in report_files:
            m = re.search(r"\d{4}-\d{2}-\d{2}", report_file.stem)
            date_str = m.group(0) if m else report_file.stem
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
        tz = load_profile_timezone()

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

                yaml_match = re.search(r"^---\s*\n(.*?)\n---", raw_content, re.DOTALL)
                if yaml_match:
                    yaml_content = yaml_match.group(1)
                    created_match = re.search(
                        r'created_time:\s*["\']?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z?["\']?',
                        yaml_content,
                    )
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

                workout_match = re.search(
                    r"###\s*🏋️\s*Workout\s*\n(.*?)(?=\n###|\n##|\n---|\Z)",
                    raw_content,
                    re.DOTALL | re.IGNORECASE,
                )

                if not workout_match:
                    workout_match = re.search(
                        r"###\s*Workout\s*\n(.*?)(?=\n###|\n##|\n---|\Z)",
                        raw_content,
                        re.DOTALL | re.IGNORECASE,
                    )

                if not workout_match:
                    workout_match = re.search(
                        r"##\s*🏋️\s*Workout\s*\n(.*?)(?=\n###|\n##|\n---|\Z)",
                        raw_content,
                        re.DOTALL | re.IGNORECASE,
                    )

                if not workout_match:
                    workout_match = re.search(
                        r"##\s*Workout\s*\n(.*?)(?=\n###|\n##|\n---|\Z)",
                        raw_content,
                        re.DOTALL | re.IGNORECASE,
                    )

                if workout_match:
                    workout_content = workout_match.group(1).strip()
                    lines = workout_content.split("\n")
                    meaningful_lines = [l.strip() for l in lines if l.strip() and not l.strip().startswith(">")]

                    if meaningful_lines:
                        workout_summary = "\n".join(meaningful_lines[:15])
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
                        r"\*\*Workout\*\*[:：]?\s*([^\n]+(?:\n(?!\*\*)[^\n]+)*)",
                        r"- \*\*Workout\*\*[:：]?\s*([^\n]+)",
                        r"Workout[:：]\s*([^\n]+)",
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
                        insights_pattern = r"- \*\*Workout\*\*[:：]?\s*([^\n]+)"
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
        if not any(p.exists() for p in self.history_files):
            return ""

        tz = load_profile_timezone()

        cutoff_date = datetime.datetime.now(tz) - datetime.timedelta(days=days)
        cutoff_str = cutoff_date.strftime("%Y-%m-%dT%H:%M:%S")

        entries = []
        try:
            for history_path in self.history_files:
                if not history_path.exists():
                    continue
                with open(history_path, "r", encoding="utf-8") as f:
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
        entries = sorted(entries, key=lambda e: e.get("timestamp", ""))
        for entry in entries[-10:]:
            timestamp = entry.get("timestamp", "Unknown")
            stats = entry.get("stats", {})
            details = entry.get("details", [])

            summary_parts.append(f"- {timestamp}: Created {stats.get('created_count', 0)}, Updated {stats.get('updated_count', 0)}")
            for detail in details[:3]:
                summary_parts.append(f"  - {detail.get('title', 'Untitled')} ({detail.get('action', 'Unknown')})")

        return "\n".join(summary_parts)

    def localize_text_timestamps(self, text: str) -> str:
        tz = load_profile_timezone()

        pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?"

        def repl(match):
            try:
                timestamp_str = match.group(0)
                dt = datetime.datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                local_dt = dt.astimezone(tz)
                return local_dt.strftime("%Y-%m-%d %H:%M:%S") + " (当地时间)"
            except Exception:
                return match.group(0)

        return re.sub(pattern, repl, text)
