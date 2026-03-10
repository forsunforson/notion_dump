import re
import uuid
from typing import Optional


_UUID32_RE = re.compile(r"^[a-fA-F0-9]{32}$")


def normalize_uuid(id_str: str | None) -> Optional[str]:
    if not id_str:
        return None
    s = str(id_str).strip()
    if not s:
        return None
    try:
        return str(uuid.UUID(s))
    except ValueError:
        pass

    compact = s.replace("-", "")
    if len(compact) == 32 and _UUID32_RE.match(compact):
        try:
            return str(uuid.UUID(compact))
        except ValueError:
            return s
    return s
