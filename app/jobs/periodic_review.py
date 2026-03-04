import os
import re
import logging
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import yaml

from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

OUTPUT_DIR = "notion_output"
REPORTS_DIR = "_reports"

LOCAL_TIMEZONE = "Asia/Shanghai"

DIARY_TAGS = {"Diary", "日记"}
DIARY_TYPE_FIELD = "type"
DIARY_TYPE_VALUES = {"diary", "Diary", "日记"}
TITLE_FALLBACK_VALUES = {"Daily Entry"}

PERIODIC_REVIEW_SYSTEM_PROMPT = os.getenv("PERIODIC_REVIEW_SYSTEM_PROMPT", "").strip() or (
    """
    # Role (角色定位)
你是一位顶尖的个人效能教练与心理分析师。你擅长从碎片化的日常记录中发现潜在的思维模式、情绪周期和行为反馈循环。你客观、敏锐，既能共情用户的低谷，也能冷峻地指出认知盲区。

# Task (任务目标)
我将提供过去一段时间内按时间顺序排列的日记。请通读这些日记，进行深度的阶段性回顾与洞察分析。

# Analysis Framework (分析框架与输出结构)
请严格按照以下 Markdown 格式输出你的分析报告，语气保持“专业、精炼、直击要害”：

## 1. 📊 周期执行摘要 (Executive Summary)
* 用一段话总结这个周期内的核心主线（例如：专注于某项工作、情绪波动较大、或者处于某种转变期）。
* 提取出这个周期内被高频提及的 3 个“关键词”。

## 2. 🧠 情绪与心理状态洞察 (Emotional & Cognitive Analysis)
* **情绪主色调**：这段时间的主导情绪是什么？（焦虑、平静、专注、亢奋等）
* **波峰与波谷**：明确指出哪几天情绪/精力最好，哪几天最差，并**深入分析触发这些波动的根本原因**（Trigger）。
* **认知盲区/思维反刍**：指出日记中反复出现的担忧、自我怀疑或不理性的认知模式（如果有）。

## 3. 🏋️ 行为与精力系统回顾 (Behavioral & Energy System)
*(注：结合用户的身体基线与目标进行评估)*
* **精力管理**：睡眠、饮食、运动对日常精力的影响模式是什么？有没有发现明显的“正反馈”或“负反馈”循环？
* **执行力**：设定的日常计划（如训练、Notion Dump 开发等）执行情况如何？阻力通常出现在哪个环节？

## 4. 💡 深度洞察与模式识别 (Deep Insights & Pattern Recognition)
* 跨越单篇日记的视角，你观察到了什么连用户自己都没意识到的潜在规律？
* 用户的注意力分配，是否与其长期的“财务自由/身体素质”目标相匹配？

## 5. 🎯 行动建议 (Actionable Outlook)
基于上述分析，使用 Start / Stop / Continue 框架给出具体的指导：
* **🟢 Start (开始做)**：一个可以立刻提升当前状态的小微行动。
* **🔴 Stop (停止做)**：一个正在消耗能量或引发负面情绪的习惯/思维。
* **🔵 Continue (继续做)**：当前做得很好，需要保持的优质策略。

# Constraints (约束)
* 不要复述日记的流水账，我要的是**归纳、提炼和洞察**。
* 保持排版的美观，多使用列表和加粗突出重点。
* 考虑到用户是程序员与价值投资者，请多使用系统思维、复利、反馈杠杆、期望值等理性概念来阐述心理学现象。
    """
)

TOKEN_ESTIMATE_WARN_THRESHOLD = 30000


class PeriodicReviewJob:
    def __init__(self):
        self.tz = ZoneInfo(LOCAL_TIMEZONE)

    async def run(self, start_date: datetime.date, end_date: datetime.date) -> str:
        start_utc, end_utc = self._local_date_range_to_utc(start_date, end_date)

        md_files = self._list_markdown_files()
        logger.info(f"Found {len(md_files)} markdown files under {OUTPUT_DIR}/")

        diary_entries = []
        for md_file in md_files:
            try:
                raw = md_file.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to read file {md_file}: {e}")
                continue

            frontmatter, body = self._parse_frontmatter(raw)
            if not frontmatter:
                continue
            if not self._is_diary(frontmatter):
                continue

            created_utc = self._parse_created_time_utc(frontmatter)
            if not created_utc:
                continue
            if not (start_utc <= created_utc < end_utc):
                continue

            title = self._get_title(frontmatter, md_file)
            local_date = created_utc.astimezone(self.tz).date().isoformat()
            cleaned_body = self._clean_body(body, title)

            diary_entries.append(
                {
                    "created_utc": created_utc,
                    "local_date": local_date,
                    "title": title,
                    "body": cleaned_body,
                }
            )

        diary_entries.sort(key=lambda x: x["created_utc"])
        logger.info(f"Selected {len(diary_entries)} diary entries in range.")

        reports_dir = Path(REPORTS_DIR)
        reports_dir.mkdir(parents=True, exist_ok=True)
        out_path = reports_dir / f"periodic_review_{start_date.isoformat()}_{end_date.isoformat()}.md"

        if not diary_entries:
            out_path.write_text(
                f"# Periodic Review ({start_date.isoformat()} ~ {end_date.isoformat()})\n\n未找到符合条件的日记文件。\n",
                encoding="utf-8",
            )
            return str(out_path)

        joined = self._join_entries(diary_entries)
        token_est = max(1, len(joined) // 2)
        if token_est > TOKEN_ESTIMATE_WARN_THRESHOLD:
            logger.warning(
                f"Prompt may be too long for local models: estimated_tokens={token_est}, chars={len(joined)}"
            )

        user_prompt = (
            f"请根据以下时间范围内的日记内容生成阶段性回顾报告。\n"
            f"时间范围（本地时间 {LOCAL_TIMEZONE}）：{start_date.isoformat()} ~ {end_date.isoformat()}\n\n"
            f"{joined}"
        )

        llm = LLMService()
        report_md = await llm.ask_text(
            PERIODIC_REVIEW_SYSTEM_PROMPT,
            user_prompt,
            max_tokens=20000,
        )
        report_md = (report_md or "").strip()

        if not report_md:
            out_path.write_text(
                f"# Periodic Review ({start_date.isoformat()} ~ {end_date.isoformat()})\n\nLLM 返回为空。\n",
                encoding="utf-8",
            )
            return str(out_path)

        out_path.write_text(report_md + "\n", encoding="utf-8")
        return str(out_path)

    def _list_markdown_files(self) -> list[Path]:
        output_dir = Path(OUTPUT_DIR)
        if not output_dir.exists():
            logger.warning(f"Output directory not found: {output_dir}")
            return []
        return list(output_dir.glob("**/*.md"))

    def _parse_frontmatter(self, content: str) -> tuple[dict, str]:
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if not match:
            return {}, content
        try:
            data = yaml.safe_load(match.group(1)) or {}
        except Exception:
            return {}, content
        body = content[match.end() :]
        return (data if isinstance(data, dict) else {}), body

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

    def _is_diary(self, frontmatter: dict) -> bool:
        type_value = frontmatter.get(DIARY_TYPE_FIELD)
        if isinstance(type_value, str) and type_value.strip() in DIARY_TYPE_VALUES:
            return True

        tags_value = frontmatter.get("tags")
        if isinstance(tags_value, list):
            for t in tags_value:
                if isinstance(t, str) and t.strip() in DIARY_TAGS:
                    return True

        title = frontmatter.get("title")
        if isinstance(title, str) and title.strip() in TITLE_FALLBACK_VALUES:
            return True

        return False

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
        for e in entries:
            parts.append(f"### [{e['local_date']}] {e['title']}\n{e['body']}\n\n---\n")
        return "\n".join(parts).strip() + "\n"
