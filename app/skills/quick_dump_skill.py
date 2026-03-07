import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import yaml

from app.core.paths import output_dir
from app.services.notion_service import NotionService


QuickDumpCategory = Literal["reflection", "idea", "vent", "journal"]


def _load_profile_timezone() -> str:
    try:
        profile_path = Path(os.getenv("PROFILE_YAML_PATH") or (Path(__file__).parent.parent.parent / "config" / "profile.yaml"))
        if profile_path.exists():
            profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
            return profile.get("preferences", {}).get("timezone", "Asia/Shanghai")
    except Exception:
        pass
    return "Asia/Shanghai"


def save_reflection_record(
    content: str,
    category: QuickDumpCategory = "reflection",
    source: str = "Telegram",
    context_question: str = "",
) -> str:
    """
    Save user's raw reflection/idea/vent/journal content into Notion Inbox.

    context_question is used to carry the original question / quoted message that the user is replying to.
    If it is not empty, it MUST be passed through verbatim (do not rewrite, summarize, or truncate).
    """
    if content is None or not str(content).strip():
        return "Error: empty content."

    state_path = output_dir() / "quick_dump_dedupe.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)

    timezone_str = _load_profile_timezone()
    tz = ZoneInfo(timezone_str)
    captured_at = datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    content_str = str(content)
    context_str = str(context_question or "")
    dedupe_key = hashlib.sha256(f"{category}\n{context_str}\n{content_str}".encode("utf-8")).hexdigest()

    try:
        state: dict = {}
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8") or "{}") or {}

        recent: dict = state.get("recent", {}) if isinstance(state.get("recent", {}), dict) else {}
        existing_ts = recent.get(dedupe_key)
        if isinstance(existing_ts, str):
            try:
                existing_dt = datetime.datetime.fromisoformat(existing_ts.replace("Z", "+00:00"))
                now_dt = datetime.datetime.now(tz)
                if (now_dt - existing_dt).total_seconds() <= 600:
                    return f"记录已成功存入大脑（去重命中），时间戳：{existing_ts}"
            except Exception:
                pass

        notion = NotionService()
        result = notion.append_to_daily_inbox(
            content=content_str,
            source=source,
            category=category,
            context_question=context_str,
        )
        page_id = result.get("page_id") or ""
        url = result.get("url") or ""
        captured_at = result.get("captured_at") or captured_at

        recent[dedupe_key] = captured_at
        if len(recent) > 200:
            items = list(recent.items())
            items.sort(key=lambda kv: kv[1], reverse=True)
            recent = dict(items[:200])
        state["recent"] = recent
        state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

        suffix = url or page_id
        if suffix:
            return f"记录已成功存入大脑，时间戳：{captured_at}，Notion：{suffix}"
        return f"记录已成功存入大脑，时间戳：{captured_at}"
    except Exception as e:
        return f"Error saving record: {str(e)}"


QUICK_DUMP_SKILL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "save_reflection_record",
        "description": "Save user's raw reflection/idea/vent/journal content into Notion Inbox. Must be called whenever user is self-recording or answering review questions.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "User's full raw text. Preserve verbatim."
                },
                "context_question": {
                    "type": "string",
                    "description": "The original question / quoted message the user is replying to. If present, preserve verbatim."
                },
                "category": {
                    "type": "string",
                    "enum": ["reflection", "idea", "vent", "journal"],
                    "description": "Record category."
                },
                "source": {
                    "type": "string",
                    "description": "Capture source, defaults to Telegram."
                }
            },
            "required": ["content"]
        }
    }
}
