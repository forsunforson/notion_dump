import re
import yaml


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(content: str) -> tuple[dict, str]:
    match = _FRONTMATTER_RE.match(content or "")
    if not match:
        return {}, content or ""
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except Exception:
        return {}, content or ""
    body = (content or "")[match.end() :]
    return (data if isinstance(data, dict) else {}), body


def parse_frontmatter_meta(content: str) -> dict:
    return parse_frontmatter(content)[0]


def _normalize_body(content: str) -> str:
    _, body = parse_frontmatter(content or "")
    return body.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def is_change(old_content: str, new_content: str) -> bool:
    return _normalize_body(old_content) != _normalize_body(new_content)
