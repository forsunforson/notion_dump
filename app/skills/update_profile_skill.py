import datetime
import json
import os
from pathlib import Path
from typing import Any, Literal
 
import yaml

from app.core.paths import project_root as _project_root, output_dir
from app.utils.plain import to_plain


UpdateProfileCategory = Literal["update", "add"]
 
 
def _is_static_locked_path(path: str) -> bool:
    p = (path or "").strip()
    if not p:
        return False
    if p in {"name", "personal_info.birth_date", "gender", "height", "timezone"}:
        return True
    last = p.split(".")[-1].strip()
    return last in {"gender", "height", "timezone"}
 
 
def update_profile_attribute(
    yaml_path: str,
    new_value: Any,
    reason: str,
    category: UpdateProfileCategory = "update",
) -> str:
    """
    Update config/profile.yaml at yaml_path (dot-notation) and append an audit record to notion_output/profile_changelog.jsonl.
    """
    target_path = (yaml_path or "").strip()
    if not target_path:
        return "Error: yaml_path is empty."
 
    reason_str = (reason or "").strip()
    if not reason_str:
        return "Error: reason is required."
 
    if _is_static_locked_path(target_path):
        return f"Error: static field is locked and cannot be modified: {target_path}"
 
    root = _project_root()
    profile_path = Path(os.getenv("PROFILE_YAML_PATH") or (root / "config" / "profile.yaml"))
    changelog_path = output_dir() / "profile_changelog.jsonl"
 
    if not profile_path.exists():
        return f"Error: profile.yaml not found: {profile_path}"
 
    try:
        try:
            from ruamel.yaml import YAML  # type: ignore
            from ruamel.yaml.comments import CommentedMap  # type: ignore
 
            ryaml = YAML()
            ryaml.preserve_quotes = True
            ryaml.indent(mapping=2, sequence=4, offset=2)
            with open(profile_path, "r", encoding="utf-8") as f:
                data = ryaml.load(f) or CommentedMap()
            if not isinstance(data, dict):
                return "Error: profile.yaml root must be a mapping."
 
            parts = [p.strip() for p in target_path.split(".") if p.strip()]
            if not parts:
                return "Error: invalid yaml_path."
 
            cursor: Any = data
            for key in parts[:-1]:
                if not isinstance(cursor, dict):
                    return f"Error: path segment is not a mapping: {key}"
                if key not in cursor or cursor[key] is None:
                    cursor[key] = CommentedMap()
                elif not isinstance(cursor[key], dict):
                    return f"Error: cannot traverse into non-mapping key: {key}"
                cursor = cursor[key]
 
            last_key = parts[-1]
            if not isinstance(cursor, dict):
                return "Error: parent path is not a mapping."
 
            old_value = cursor.get(last_key) if isinstance(cursor, dict) else None
            cursor[last_key] = new_value
 
            with open(profile_path, "w", encoding="utf-8") as f:
                ryaml.dump(data, f)

            old_plain = to_plain(old_value)
            new_plain = to_plain(new_value)
        except Exception:
            with open(profile_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                return "Error: profile.yaml root must be a mapping."
 
            parts = [p.strip() for p in target_path.split(".") if p.strip()]
            if not parts:
                return "Error: invalid yaml_path."
 
            cursor = data
            for key in parts[:-1]:
                nxt = cursor.get(key)
                if nxt is None:
                    cursor[key] = {}
                    nxt = cursor[key]
                if not isinstance(nxt, dict):
                    return f"Error: cannot traverse into non-mapping key: {key}"
                cursor = nxt
 
            last_key = parts[-1]
            old_value = cursor.get(last_key)
            cursor[last_key] = new_value
 
            with open(profile_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

            old_plain = to_plain(old_value)
            new_plain = to_plain(new_value)

        changelog_path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "yaml_path": target_path,
            "old_value": old_plain,
            "new_value": new_plain,
            "reason": reason_str,
            "source": "Telegram Bot",
        }
        with open(changelog_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
 
        return f"OK: updated {target_path}"
    except Exception as e:
        return f"Error updating profile: {str(e)}"
 
 
UPDATE_PROFILE_SKILL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "update_profile_attribute",
        "description": "Update config/profile.yaml using dot-notation yaml_path. Must be used when user changes goals, preferences, philosophies, projects, or introduces new custom traits.",
        "parameters": {
            "type": "object",
            "properties": {
                "yaml_path": {
                    "type": "string",
                    "description": "Target yaml key path using dot notation, e.g. 'recent_focus.weekly_goal' or 'custom_traits.new_rule'.",
                },
                "new_value": {
                    "description": "New value to set. Can be string, boolean, number, list, or object.",
                    "anyOf": [
                        {"type": "string"},
                        {"type": "boolean"},
                        {"type": "number"},
                        {"type": "array"},
                        {"type": "object"},
                        {"type": "null"},
                    ],
                },
                "reason": {
                    "type": "string",
                    "description": "The user's underlying motivation for this change. Must be precise.",
                },
                "category": {
                    "type": "string",
                    "enum": ["update", "add"],
                    "description": "Operation type: update existing value or add new trait.",
                },
            },
            "required": ["yaml_path", "new_value", "reason"],
        },
    },
}
