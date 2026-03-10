from typing import Any, Dict, Optional


def extract_title(obj: Dict[str, Any]) -> str:
    """
    Extract title from a Notion page or database object.
    """
    if not obj:
        return "Unknown"

    obj_type = obj.get("object")

    if obj_type == "page":
        properties = obj.get("properties", {})
        # First try standard names
        title_prop = properties.get("title") or properties.get("Name")
        if title_prop and title_prop.get("type") == "title":
            return _extract_plain_text(title_prop.get("title", [])) or "Untitled"

        # Fallback: iterate all properties to find type='title'
        for prop in properties.values():
            if prop.get("type") == "title":
                return _extract_plain_text(prop.get("title", [])) or "Untitled"
        
        return "Untitled"

    elif obj_type == "database":
        return _extract_plain_text(obj.get("title", [])) or "Untitled Database"

    return "Unknown"


def _extract_plain_text(rich_text_list: list) -> str:
    if not rich_text_list:
        return ""
    return "".join([t.get("plain_text", "") for t in rich_text_list])


def get_page_meta(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract common metadata from a Notion object.
    """
    return {
        "title": extract_title(obj),
        "created_time": obj.get("created_time"),
        "last_edited_time": obj.get("last_edited_time"),
        "type": obj.get("object", "unknown"),
        "object": obj,
    }
