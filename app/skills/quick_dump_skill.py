import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Literal

from app.services.notion_service import NotionService


QuickDumpCategory = Literal["reflection", "idea", "vent", "journal"]


def save_reflection_record(content: str, category: str = "reflection", source: str = "Telegram") -> dict:
    if content is None or not str(content).strip():
        # 修改点 1：返回字典而不是字符串
        return {"status": "error", "message": "Error: empty content."}

    project_root = Path(os.getcwd())
    state_path = project_root / "notion_output" / "quick_dump_dedupe.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)

    captured_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    content_str = str(content)
    dedupe_key = hashlib.sha256(f"{category}\n{content_str}".encode("utf-8")).hexdigest()

    try:
        state: dict = {}
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8") or "{}") or {}

        recent: dict = state.get("recent", {}) if isinstance(state.get("recent", {}), dict) else {}
        existing_ts = recent.get(dedupe_key)
        if isinstance(existing_ts, str):
            try:
                existing_dt = datetime.datetime.fromisoformat(existing_ts.replace("Z", "+00:00"))
                now_dt = datetime.datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
                if (now_dt - existing_dt).total_seconds() <= 600:
                    # 修改点 2：返回字典
                    return {
                        "status": "success", 
                        "message": f"记录已成功存入大脑（去重命中），时间戳：{existing_ts}"
                    }
            except Exception:
                pass

        notion = NotionService()
        result = notion.append_to_inbox(content=content_str, source=source, category=category)
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
            # 修改点 3：返回字典
            return {
                "status": "success", 
                "message": f"记录已成功存入大脑，时间戳：{captured_at}，Notion：{suffix}"
            }
        
        # 修改点 4：返回字典
        return {
            "status": "success", 
            "message": f"记录已成功存入大脑，时间戳：{captured_at}"
        }
        
    except Exception as e:
        # 修改点 5：返回字典
        return {"status": "error", "message": f"Error saving record: {str(e)}"}


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

