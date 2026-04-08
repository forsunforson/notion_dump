import datetime
import json
import logging
import re
from pathlib import Path
from typing import Any

from app.core.paths import reports_dir
from app.utils.frontmatter import parse_frontmatter
from app.utils.timezone_utils import load_profile_timezone

logger = logging.getLogger(__name__)


class IndexGeneratorService:
    INDEX_SYSTEM_PROMPT = (
        "你是一个文档索引生成器。"
        "你的任务是为单篇 Markdown 文档生成简短索引信息。"
        "只返回 JSON，不要输出任何额外文本。"
    )

    INDEX_USER_PROMPT_TEMPLATE = """
请阅读以下文档，生成索引信息。

要求：
1. `summary` 必须是一句中文总结，简短、客观，不要超过 50 字。
2. `tags` 必须是 3 到 5 个字符串标签。
3. 禁止捏造文档中不存在的信息。
4. 仅返回以下 JSON 结构：
{{
  "summary": "一句话总结",
  "tags": ["tag1", "tag2", "tag3"]
}}

文件名：{filename}

<frontmatter>
{frontmatter_json}
</frontmatter>

<body>
{body}
</body>
""".strip()

    def __init__(
        self,
        *,
        index_path: Path | None = None,
        llm_service: Any | None = None,
        use_llm: bool = True,
    ):
        self.index_path = index_path or (reports_dir() / "index.json")
        self.llm = llm_service if llm_service is not None else (self._init_llm() if use_llm else None)
        self.tz = load_profile_timezone()

    def _init_llm(self):
        try:
            from app.services.llm_service import LLMService

            return LLMService()
        except Exception as e:
            logger.warning(f"IndexGeneratorService LLM unavailable, fallback mode enabled: {e}")
            return None

    def load_index(self) -> dict[str, dict[str, Any]]:
        if not self.index_path.exists():
            return {}
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to read index file {self.index_path}: {e}")
            return {}
        return data if isinstance(data, dict) else {}

    def save_index(self, data: dict[str, dict[str, Any]]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        ordered = dict(sorted(data.items(), key=lambda item: item[0]))
        self.index_path.write_text(
            json.dumps(ordered, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    async def update_files(self, file_paths: list[str | Path]) -> dict[str, dict[str, Any]]:
        index_data = self.load_index()
        for raw_path in file_paths or []:
            path = Path(raw_path)
            if not path.exists() or path.suffix.lower() != ".md":
                continue
            index_data[path.name] = await self.build_entry(path)
        self.save_index(index_data)
        return index_data

    async def build_entry(self, file_path: str | Path) -> dict[str, Any]:
        path = Path(file_path)
        raw = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(raw)
        summary, tags = await self._summarize_and_tag(path=path, frontmatter=frontmatter, body=body)
        return {
            "summary": summary,
            "tags": tags,
            "date": self._extract_date(frontmatter),
        }

    async def _summarize_and_tag(self, *, path: Path, frontmatter: dict[str, Any], body: str) -> tuple[str, list[str]]:
        if self.llm is not None:
            try:
                payload = await self.llm.ask_json(
                    self.INDEX_SYSTEM_PROMPT,
                    self.INDEX_USER_PROMPT_TEMPLATE.format(
                        filename=path.name,
                        frontmatter_json=json.dumps(frontmatter, ensure_ascii=False, indent=2),
                        body=(body or "").strip()[:6000],
                    ),
                )
                summary = self._normalize_summary(payload.get("summary"))
                tags = self._normalize_tags(payload.get("tags"), frontmatter=frontmatter, path=path)
                if summary and 3 <= len(tags) <= 5:
                    return summary, tags
            except Exception as e:
                logger.warning(f"Index generation via LLM failed for {path}: {e}")
        return self._fallback_summary(frontmatter=frontmatter, body=body), self._fallback_tags(
            frontmatter=frontmatter, body=body, path=path
        )

    def _extract_date(self, frontmatter: dict[str, Any]) -> str | None:
        for key in ("last_edited_time", "date", "trade_date", "transaction_date", "created_time"):
            value = frontmatter.get(key)
            if value is None:
                continue
            resolved = self._to_local_date(value)
            if resolved:
                return resolved
        return None

    def _to_local_date(self, value: Any) -> str | None:
        if isinstance(value, datetime.datetime):
            dt = value
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt.astimezone(self.tz).date().isoformat()

        if isinstance(value, datetime.date):
            return value.isoformat()

        if not isinstance(value, str):
            return None

        s = value.strip()
        if not s:
            return None
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return s

        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.datetime.fromisoformat(s)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(self.tz).date().isoformat()

    def _fallback_summary(self, *, frontmatter: dict[str, Any], body: str) -> str:
        title = str(frontmatter.get("title") or "").strip()
        lines = []
        for line in (body or "").splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                continue
            lines.append(line)
            if len(" ".join(lines)) >= 80:
                break
        content = " ".join(lines).strip()
        if not content:
            return self._normalize_summary(f"{title or '该文档'}暂无可提炼的正文摘要。")
        if title and content.startswith(title):
            return self._normalize_summary(content)
        prefix = f"{title}: " if title else ""
        return self._normalize_summary(prefix + content)

    def _fallback_tags(self, *, frontmatter: dict[str, Any], body: str, path: Path) -> list[str]:
        tags: list[str] = []

        raw_tags = frontmatter.get("tags")
        if isinstance(raw_tags, list):
            for item in raw_tags:
                if isinstance(item, str) and item.strip():
                    tags.append(item.strip())

        for key in ("type", "status", "category", "action"):
            value = frontmatter.get(key)
            if isinstance(value, str) and value.strip():
                tags.append(value.strip())

        title = str(frontmatter.get("title") or "").strip()
        if title:
            tags.extend(self._extract_title_keywords(title))

        lower_body = (body or "").lower()
        if "trade snapshot log" in lower_body:
            tags.append("trade")
        if self._looks_like_diary(frontmatter):
            tags.append("diary")

        return self._normalize_tags(tags, frontmatter=frontmatter, path=path)

    def _normalize_summary(self, summary: Any) -> str:
        text = ""
        if isinstance(summary, str):
            text = summary.strip()
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return ""
        if len(text) > 80:
            text = text[:79].rstrip() + "…"
        return text

    def _normalize_tags(self, tags: Any, *, frontmatter: dict[str, Any], path: Path) -> list[str]:
        items: list[str] = []
        if isinstance(tags, list):
            candidates = tags
        elif isinstance(tags, str):
            candidates = [x.strip() for x in re.split(r"[,，/\n]", tags) if x.strip()]
        else:
            candidates = []

        for item in candidates:
            if not isinstance(item, str):
                continue
            cleaned = re.sub(r"\s+", " ", item).strip().strip("#")
            if cleaned:
                items.append(cleaned[:32])

        for fallback in self._fallback_fill_tags(frontmatter=frontmatter, path=path):
            if len(items) >= 5:
                break
            items.append(fallback)

        unique: list[str] = []
        seen: set[str] = set()
        for item in items:
            key = item.casefold()
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
            if len(unique) >= 5:
                break

        if len(unique) < 3:
            for filler in ("note", "notion", "document"):
                if filler.casefold() in seen:
                    continue
                unique.append(filler)
                seen.add(filler.casefold())
                if len(unique) >= 3:
                    break
        return unique[:5]

    def _fallback_fill_tags(self, *, frontmatter: dict[str, Any], path: Path) -> list[str]:
        out: list[str] = []
        if self._looks_like_diary(frontmatter):
            out.append("diary")
        title = str(frontmatter.get("title") or "").strip()
        out.extend(self._extract_title_keywords(title))
        out.extend([path.stem[:24], "note", "notion", "document"])
        return [x for x in out if x]

    def _extract_title_keywords(self, title: str) -> list[str]:
        raw = re.split(r"[\s/_,:;|()\[\]{}\-]+", title or "")
        return [token.strip()[:24] for token in raw if token.strip()][:2]

    def _looks_like_diary(self, frontmatter: dict[str, Any]) -> bool:
        title = str(frontmatter.get("title") or "").strip()
        type_value = str(frontmatter.get("type") or "").strip()
        tags = frontmatter.get("tags") or []
        return (
            title == "Daily Entry"
            or type_value.lower() == "diary"
            or any(isinstance(tag, str) and tag.strip() in {"Diary", "日记"} for tag in tags)
        )
