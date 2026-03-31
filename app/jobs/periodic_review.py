import re
import json
import logging
import datetime
from collections import Counter, defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo
import yaml

from app.core.paths import output_dir as _output_dir, reports_dir as _reports_dir
from app.services.llm_service import LLMService
from app.services.prompt_manager import PromptManager
from app.services.context_fetcher import ContextFetcher
from app.utils.jsonl_event_store import read_jsonl_grouped_by_date
from app.utils.timezone_utils import load_profile_timezone

logger = logging.getLogger(__name__)

OUTPUT_DIR = _output_dir()
REPORTS_DIR = _reports_dir()
METRICS_FILENAME = "metrics.jsonl"

LOCAL_TIMEZONE = "Asia/Shanghai"

REVIEW_TYPES = {"daily", "weekly", "monthly", "custom"}

TOKEN_ESTIMATE_WARN_THRESHOLD = 30000


class PeriodicReviewJob:
    def __init__(self, review_type: str = "custom"):
        review_type = (review_type or "").strip().lower()
        if review_type not in REVIEW_TYPES:
            raise ValueError(f"Invalid review_type: {review_type}. Must be one of {sorted(REVIEW_TYPES)}")

        self.review_type = review_type
        self.prompt_manager = PromptManager()
        self.tz = load_profile_timezone()
        self.output_path: Path | None = None

    async def run(
        self, start_date: datetime.date | None = None, end_date: datetime.date | None = None
    ) -> str:
        start_date, end_date = self._resolve_date_range(start_date=start_date, end_date=end_date)
        start_utc, end_utc = self._local_date_range_to_utc(start_date, end_date)

        include_trade_analysis = self.review_type in {"weekly", "monthly"}
        trade_entries: list[dict] = []
        trade_start_date: datetime.date | None = None
        trade_end_date: datetime.date | None = None
        trade_start_utc: datetime.datetime | None = None
        trade_end_utc: datetime.datetime | None = None
        if include_trade_analysis:
            trade_end_date = end_date
            trade_start_date = end_date - datetime.timedelta(days=6)
            trade_start_utc, trade_end_utc = self._local_date_range_to_utc(trade_start_date, trade_end_date)

        cf = ContextFetcher()
        filters: dict[str, object] = {
            "diary": cf.make_daily_entry_filter(start_utc=start_utc, end_utc=end_utc),
        }
        if include_trade_analysis and trade_start_utc and trade_end_utc:
            filters["trade"] = cf.make_trade_log_filter(start_utc=trade_start_utc, end_utc=trade_end_utc)

        md_count, buckets = cf.collect_markdown_by_filters(filters=filters)
        diary_entries = []
        for it in buckets.get("diary") or []:
            e = cf.build_entry(raw=it.get("raw") or "", path=it.get("path") or "<unknown>")
            if e:
                diary_entries.append(e)
        diary_entries.sort(key=lambda x: x["created_utc"])

        trade_entries = []
        for it in buckets.get("trade") or []:
            e = cf.build_entry(
                raw=it.get("raw") or "",
                path=it.get("path") or "<unknown>",
                include_path=True,
            )
            if e:
                trade_entries.append(e)
        trade_entries.sort(key=lambda x: x["created_utc"])
        logger.info(f"Found {md_count} markdown files under {OUTPUT_DIR}/")
        logger.info(f"Selected {len(diary_entries)} diary entries in range.")
        if include_trade_analysis:
            logger.info(
                f"Selected {len(trade_entries)} trade snapshot logs in range {trade_start_date} ~ {trade_end_date}."
            )

        metrics = self._load_metrics_in_range(start_date=start_date, end_date=end_date)
        logger.info(f"Selected {len(metrics)} metrics rows in range.")

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = REPORTS_DIR / f"{self.review_type}_{end_date.isoformat()}.md"
        self.output_path = out_path

        profile_text = self.prompt_manager.load_profile()
        notes_content = self._format_notes_content(diary_entries)
        metrics_trend = self._format_metrics_trend(metrics, start_date=start_date, end_date=end_date)

        messages = self.prompt_manager.build_review_prompt(
            review_type=self.review_type,
            profile=profile_text,
            metrics_trend=metrics_trend,
            notes_content=notes_content,
        )
        system_prompt = messages[0]["content"]
        user_prompt = messages[1]["content"]

        token_est = max(1, (len(system_prompt) + len(user_prompt)) // 2)
        if token_est > TOKEN_ESTIMATE_WARN_THRESHOLD:
            logger.warning(
                f"Prompt may be too long for local models: estimated_tokens={token_est}, chars={len(system_prompt) + len(user_prompt)}"
            )

        max_tokens = self._max_tokens_for_review_type(self.review_type)
        llm = LLMService()
        try:
            report_md = await llm.ask_text(
                system_prompt,
                user_prompt,
                max_tokens=max_tokens,
            )
        except Exception as e:
            logger.error(f"Failed to generate review via LLM: {e}")
            report_md = ""
        report_md = (report_md or "").strip()

        if not report_md:
            if self.review_type == "daily":
                report_md = (
                    "## ☕ 昨日浓缩 (Daily Espresso)\n"
                    "LLM 不可用或返回为空。\n\n"
                    "## 🎯 赛博搭子的 Vibe Check\n"
                    "LLM 不可用或返回为空。\n\n"
                    "## 💡 今日一闪 (Today's Spark)\n"
                    "今天如果只能做一件让“明天的你”更爽的事，你会选哪一件？\n"
                ).strip()
            else:
                report_md = (
                    "## 1. 冰冷的镜像 (The Objective Mirror)\n"
                    "LLM 不可用或返回为空。\n\n"
                    "## 2. 偏离警告 (The Guardian's Alert)\n"
                    "LLM 不可用或返回为空。\n\n"
                    "## 3. 灵魂拷问 (Socratic Questions)\n"
                    "1. 你真正想从这次回顾中得到什么？\n"
                ).strip()

        if include_trade_analysis and trade_entries and trade_start_date and trade_end_date:
            trade_logs_text = self._format_trade_logs_content(trade_entries)
            net_worth_cny = self._load_latest_net_worth_cny()
            trade_messages = self.prompt_manager.build_trade_analysis_prompt(
                profile=profile_text,
                trade_logs=trade_logs_text,
                as_of_date=end_date.isoformat(),
                timezone=self.tz.key,
                net_worth_cny=net_worth_cny,
            )
            trade_system_prompt = trade_messages[0]["content"]
            trade_user_prompt = trade_messages[1]["content"]
            try:
                trade_md = await llm.ask_text(
                    trade_system_prompt,
                    trade_user_prompt,
                    max_tokens=4000,
                )
            except Exception as e:
                logger.error(f"Failed to generate trade analysis via LLM: {e}")
                trade_md = ""
            trade_md = (trade_md or "").strip()
            if trade_md:
                report_md = (
                    report_md.rstrip()
                    + "\n\n## 4. 交易复盘 (Trade Log Analysis)\n\n"
                    + trade_md
                    + "\n"
                )

        out_path.write_text(report_md + "\n", encoding="utf-8")
        return report_md

    def _load_latest_net_worth_cny(self) -> float | None:
        metrics_path = OUTPUT_DIR / METRICS_FILENAME
        if not metrics_path.exists():
            return None

        latest_dt: datetime.datetime | None = None
        latest_val: float | None = None
        try:
            with open(metrics_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = (line or "").strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    v = obj.get("net_worth_cny")
                    if not isinstance(v, (int, float)) or isinstance(v, bool):
                        continue
                    ts = obj.get("timestamp")
                    if not isinstance(ts, str) or not ts.strip():
                        continue
                    s = ts.strip()
                    if s.endswith("Z"):
                        s = s[:-1] + "+00:00"
                    try:
                        dt = datetime.datetime.fromisoformat(s)
                    except ValueError:
                        continue
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=datetime.timezone.utc)
                    dt = dt.astimezone(datetime.timezone.utc)
                    if latest_dt is None or dt > latest_dt:
                        latest_dt = dt
                        latest_val = float(v)
        except Exception:
            return None
        return latest_val

    def _resolve_date_range(
        self, start_date: datetime.date | None, end_date: datetime.date | None
    ) -> tuple[datetime.date, datetime.date]:
        today_local = datetime.datetime.now(self.tz).date()

        if start_date is not None and end_date is not None:
            if start_date > end_date:
                raise ValueError("start_date must be <= end_date")
            return start_date, end_date

        if self.review_type == "daily":
            d = today_local - datetime.timedelta(days=1)
            return d, d

        if self.review_type == "weekly":
            last_sunday = today_local - datetime.timedelta(days=today_local.isoweekday())
            last_monday = last_sunday - datetime.timedelta(days=6)
            return last_monday, last_sunday

        if self.review_type == "monthly":
            first_day_this_month = today_local.replace(day=1)
            last_day_prev_month = first_day_this_month - datetime.timedelta(days=1)
            first_day_prev_month = last_day_prev_month.replace(day=1)
            return first_day_prev_month, last_day_prev_month

        raise ValueError("custom review_type requires start_date and end_date")

    def _list_markdown_files(self) -> list[Path]:
        if not OUTPUT_DIR.exists():
            logger.warning(f"Output directory not found: {OUTPUT_DIR}")
            return []
        return list(OUTPUT_DIR.glob("**/*.md"))

    def _parse_created_time_utc(self, frontmatter: dict) -> datetime.datetime | None:
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

    def _local_date_range_to_utc(
        self, start_date: datetime.date, end_date: datetime.date
    ) -> tuple[datetime.datetime, datetime.datetime]:
        start_local = datetime.datetime.combine(start_date, datetime.time.min).replace(tzinfo=self.tz)
        end_local_exclusive = datetime.datetime.combine(
            end_date + datetime.timedelta(days=1), datetime.time.min
        ).replace(tzinfo=self.tz)
        return start_local.astimezone(datetime.timezone.utc), end_local_exclusive.astimezone(datetime.timezone.utc)

    def _get_title(self, frontmatter: dict, md_file: Path) -> str:
        title = frontmatter.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        return md_file.stem

    def _clean_body(self, body: str, title: str) -> str:
        if not body:
            return ""
        stripped = body.lstrip()
        if stripped.startswith("# "):
            first_line = stripped.splitlines()[0][2:].strip()
            if first_line == title:
                stripped = "\n".join(stripped.splitlines()[1:]).lstrip("\n")
        return stripped.strip()

    def _join_entries(self, entries: list[dict]) -> str:
        parts = []
        if not entries:
            return "## Diary Entries\n\n未找到符合条件的日记。\n"
        parts.append("## Diary Entries\n")
        for e in entries:
            parts.append(f"### [{e['local_date']}] {e['title']}\n{e['body']}\n\n---\n")
        return "\n".join(parts).strip() + "\n"

    def _load_metrics_in_range(self, start_date: datetime.date, end_date: datetime.date) -> list[dict]:
        metrics_path = OUTPUT_DIR / METRICS_FILENAME
        if not metrics_path.exists():
            return []

        try:
            return read_jsonl_grouped_by_date(
                metrics_path, start_date=start_date, end_date=end_date, tz=self.tz
            )
        except Exception as e:
            logger.error(f"Error reading metrics file {metrics_path}: {e}")
            return []

    def _extract_metric_date(self, metric: dict) -> datetime.date | None:
        if not isinstance(metric, dict):
            return None

        date_value = metric.get("date")
        if isinstance(date_value, str) and date_value.strip():
            try:
                return datetime.date.fromisoformat(date_value.strip()[:10])
            except ValueError:
                return None

        ts_value = metric.get("timestamp")
        if isinstance(ts_value, str) and ts_value.strip():
            s = ts_value.strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            try:
                dt = datetime.datetime.fromisoformat(s)
            except ValueError:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt.astimezone(self.tz).date()

        return None

    def _format_metrics(self, metrics: list[dict]) -> str:
        if not metrics:
            return "## Metrics\n\n未找到该时间段内的 metrics.jsonl 记录。\n"
        try:
            content = json.dumps(metrics, ensure_ascii=False, indent=2)
        except Exception:
            content = "\n".join([json.dumps(m, ensure_ascii=False) for m in metrics])
        return f"## Metrics\n\n```json\n{content}\n```\n"

    def _format_notes_content(self, entries: list[dict]) -> str:
        if not entries:
            return ""

        parts: list[str] = []
        for e in entries:
            header = f"### {e['local_date']} {e['title']}".strip()
            body = (e.get("body") or "").strip()
            if body:
                parts.append(f"{header}\n{body}")
            else:
                parts.append(f"{header}\n（空）")
        return "\n\n---\n\n".join(parts).strip()

    def _format_trade_logs_content(
        self,
        entries: list[dict],
        *,
        max_entries: int = 20,
        max_chars_per_entry: int = 1800,
        max_total_chars: int = 24000,
    ) -> str:
        if not entries:
            return ""

        if len(entries) > max_entries:
            keep_head = max_entries // 2
            keep_tail = max_entries - keep_head
            sliced = list(entries[:keep_head]) + [{"__ellipsis__": True}] + list(entries[-keep_tail:])
        else:
            sliced = list(entries)

        parts: list[str] = []
        total = 0
        for e in sliced:
            if e.get("__ellipsis__"):
                parts.append("...\n(…中间省略)\n...")
                continue
            header = f"### {e.get('local_date','').strip()} {e.get('title','').strip()}".strip()
            body = (e.get("body") or "").strip()
            if len(body) > max_chars_per_entry:
                body = body[:max_chars_per_entry].rstrip() + "\n(…截断)"
            block = f"{header}\n{body}".strip()
            if not block:
                continue
            if total + len(block) > max_total_chars:
                break
            parts.append(block)
            total += len(block)

        return "\n\n---\n\n".join(parts).strip()

    def _format_metrics_trend(
        self, metrics: list[dict], start_date: datetime.date, end_date: datetime.date
    ) -> str:
        if not metrics:
            return ""

        by_date: dict[str, list[dict]] = defaultdict(list)
        for m in metrics:
            d = self._extract_metric_date(m)
            if d is None:
                continue
            by_date[d.isoformat()].append(m)

        def is_number(v) -> bool:
            return isinstance(v, (int, float)) and not isinstance(v, bool)

        per_day_lines: list[str] = []
        numeric_series: dict[str, list[float]] = defaultdict(list)
        categorical_series: dict[str, list[str]] = defaultdict(list)

        for day in sorted(by_date.keys()):
            rows = by_date[day]
            agg_num: dict[str, list[float]] = defaultdict(list)
            agg_cat: dict[str, list[str]] = defaultdict(list)

            for row in rows:
                if not isinstance(row, dict):
                    continue
                for k, v in row.items():
                    if k in {"date", "timestamp", "source"}:
                        continue
                    if v is None:
                        continue
                    if is_number(v):
                        agg_num[k].append(float(v))
                        numeric_series[k].append(float(v))
                    elif isinstance(v, str) and v.strip():
                        agg_cat[k].append(v.strip())
                        categorical_series[k].append(v.strip())

            parts: list[str] = [f"- {day}"]
            for k in sorted(agg_num.keys()):
                vals = agg_num[k]
                if not vals:
                    continue
                if len(vals) == 1:
                    parts.append(f"{k}={vals[0]:g}")
                else:
                    avg = sum(vals) / len(vals)
                    parts.append(f"{k}≈{avg:g} (min={min(vals):g}, max={max(vals):g}, n={len(vals)})")
            for k in sorted(agg_cat.keys()):
                vals = agg_cat[k]
                if not vals:
                    continue
                mode = Counter(vals).most_common(1)[0][0]
                parts.append(f"{k}≈{mode}")

            per_day_lines.append("  ".join(parts))

        extremes: list[str] = []
        for k in sorted(numeric_series.keys()):
            vals = numeric_series[k]
            if not vals:
                continue
            extremes.append(f"- {k}: min={min(vals):g}, max={max(vals):g}, n={len(vals)}")

        range_line = f"{start_date.isoformat()} ~ {end_date.isoformat()} ({self.tz.key})"
        blocks: list[str] = [f"Range: {range_line}", "", "Daily:", *per_day_lines]
        if extremes:
            blocks.extend(["", "Extremes:", *extremes])
        return "\n".join(blocks).strip()

    def _max_tokens_for_review_type(self, review_type: str) -> int:
        if review_type == "daily":
            return 8000
        if review_type == "weekly":
            return 14000
        if review_type == "monthly":
            return 18000
        return 20000
