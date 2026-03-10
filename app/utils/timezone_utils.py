import os
from pathlib import Path
from zoneinfo import ZoneInfo
import yaml

from app.core.paths import config_dir


DEFAULT_TIMEZONE = "Asia/Shanghai"


def safe_zoneinfo(timezone_str: str | None, default: str = DEFAULT_TIMEZONE) -> ZoneInfo:
    try:
        s = (timezone_str or "").strip() or default
        return ZoneInfo(s)
    except Exception:
        return ZoneInfo(default)


def load_profile_timezone(
    profile_path: Path | None = None, default: str = DEFAULT_TIMEZONE
) -> ZoneInfo:
    path = profile_path or Path(os.getenv("PROFILE_YAML_PATH") or (config_dir() / "profile.yaml"))
    tz_str = default
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if isinstance(data, dict):
                tz_candidate = ((data.get("preferences") or {}) if isinstance(data.get("preferences"), dict) else {}).get(
                    "timezone"
                )
                if isinstance(tz_candidate, str) and tz_candidate.strip():
                    tz_str = tz_candidate.strip()
    except Exception:
        tz_str = default
    return safe_zoneinfo(tz_str, default=default)
