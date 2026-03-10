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
