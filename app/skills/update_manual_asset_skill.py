import datetime
import os
from pathlib import Path
from typing import Any, Literal

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from app.core.paths import output_dir
from app.core.paths import project_root as _project_root
from app.services.event_store import write_profile_changelog_event
from app.utils.plain import to_plain


ManualAssetKey = Literal["value", "price"]


def _normalize_new_value(old_value: Any, new_value: Any) -> Any:
    if new_value is None:
        return None
    numeric: float
    if isinstance(new_value, (int, float)):
        numeric = float(new_value)
    elif isinstance(new_value, str):
        try:
            numeric = float(new_value.strip())
        except ValueError:
            return new_value
    else:
        return new_value

    is_int_like = abs(numeric - int(numeric)) < 1e-9
    if isinstance(old_value, int):
        return int(numeric) if is_int_like else numeric
    if isinstance(old_value, float):
        return numeric
    if isinstance(old_value, str):
        return str(int(numeric)) if is_int_like else str(numeric)
    return int(numeric) if is_int_like else numeric


def _recursive_update_node(
    current_node: Any,
    asset_name: str,
    target_key: ManualAssetKey,
    new_value: Any,
    current_path: str,
) -> tuple[bool, Any, Any, str]:
    if isinstance(current_node, dict):
        name = current_node.get("name")
        if isinstance(name, str) and name.strip() == asset_name:
            old_value = current_node.get(target_key)
            normalized = _normalize_new_value(old_value, new_value)
            current_node[target_key] = normalized
            return True, old_value, normalized, current_path

        for list_key in ("asset_detail", "liability_detail", "detail"):
            items = current_node.get(list_key)
            if not isinstance(items, list):
                continue
            for idx, item in enumerate(items):
                if isinstance(item, dict):
                    child_name = item.get("name")
                    if isinstance(child_name, str) and child_name.strip():
                        seg = f"{list_key}[{child_name.strip()}]"
                    else:
                        seg = f"{list_key}[{idx}]"
                else:
                    seg = f"{list_key}[{idx}]"
                found, old, normalized, found_path = _recursive_update_node(
                    item,
                    asset_name,
                    target_key,
                    new_value,
                    f"{current_path}.{seg}",
                )
                if found:
                    return True, old, normalized, found_path

        for key, value in current_node.items():
            if key in ("asset_detail", "liability_detail", "detail"):
                continue
            if isinstance(value, dict):
                found, old, normalized, found_path = _recursive_update_node(
                    value,
                    asset_name,
                    target_key,
                    new_value,
                    f"{current_path}.{key}",
                )
                if found:
                    return True, old, normalized, found_path
            elif isinstance(value, list):
                for idx, item in enumerate(value):
                    found, old, normalized, found_path = _recursive_update_node(
                        item,
                        asset_name,
                        target_key,
                        new_value,
                        f"{current_path}.{key}[{idx}]",
                    )
                    if found:
                        return True, old, normalized, found_path

    elif isinstance(current_node, list):
        for idx, item in enumerate(current_node):
            found, old, normalized, found_path = _recursive_update_node(
                item,
                asset_name,
                target_key,
                new_value,
                f"{current_path}[{idx}]",
            )
            if found:
                return True, old, normalized, found_path

    return False, None, None, ""


def update_manual_asset_value(
    asset_name: str,
    target_key: ManualAssetKey,
    new_value: float,
    reason: str,
) -> str:
    asset_name_str = str(asset_name or "").strip()
    if not asset_name_str:
        return "Error: asset_name is required."

    if target_key not in ("value", "price"):
        return f"Error: target_key must be one of ['value', 'price'], got {target_key}"

    reason_str = str(reason or "").strip()
    if not reason_str:
        return "Error: reason is required."

    root = _project_root()
    profile_path = Path(os.getenv("PROFILE_YAML_PATH") or (root / "config" / "profile.yaml"))
    changelog_path = output_dir() / "profile_changelog.jsonl"

    if not profile_path.exists():
        return f"Error: profile.yaml not found: {profile_path}"

    try:
        ryaml = YAML()
        ryaml.preserve_quotes = True
        ryaml.indent(mapping=2, sequence=4, offset=2)

        with open(profile_path, "r", encoding="utf-8") as f:
            data = ryaml.load(f) or CommentedMap()
        if not isinstance(data, dict):
            return "Error: profile.yaml root must be a mapping."

        balance_sheet = data.get("balance_sheet_structure")
        if not isinstance(balance_sheet, dict):
            return "Error: balance_sheet_structure is missing or not a mapping."

        found, old_value, normalized_value, found_path = _recursive_update_node(
            balance_sheet,
            asset_name_str,
            target_key,
            new_value,
            "balance_sheet_structure",
        )
        if not found:
            return f"Error: asset not found: {asset_name_str}"

        with open(profile_path, "w", encoding="utf-8") as f:
            ryaml.dump(data, f)

        changelog_path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "yaml_path": f"{found_path}.{target_key}",
            "old_value": to_plain(old_value),
            "new_value": to_plain(normalized_value),
            "reason": reason_str,
            "source": "update_manual_asset_skill",
        }
        write_profile_changelog_event(changelog_path, event)

        return f"OK: updated {found_path}.{target_key}"
    except Exception as e:
        return f"Error updating manual asset: {str(e)}"


UPDATE_MANUAL_ASSET_SCHEMA = {
    "type": "function",
    "function": {
        "name": "update_manual_asset_value",
        "description": "Update offline/unlisted asset values in config/profile.yaml balance_sheet_structure (e.g., options price, car/house fund value, liabilities value).",
        "parameters": {
            "type": "object",
            "properties": {
                "asset_name": {
                    "type": "string",
                    "description": "Target asset name (matches YAML node 'name'), e.g. '字节期权', 'house fund', 'car', 'short-term liabilities'.",
                },
                "target_key": {
                    "type": "string",
                    "enum": ["value", "price"],
                    "description": "Which key to update on the matched asset node.",
                },
                "new_value": {
                    "type": "number",
                    "description": "New numeric value to set.",
                },
                "reason": {
                    "type": "string",
                    "description": "The user's underlying motivation for this change. Must be precise.",
                },
            },
            "required": ["asset_name", "target_key", "new_value", "reason"],
        },
    },
}
