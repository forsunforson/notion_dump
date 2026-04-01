import json
import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.utils.timezone_utils import load_profile_timezone


def _parse_ts_utc(ts: str) -> datetime.datetime | None:
    s = (ts or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def _event_local_date(event: dict, tz: ZoneInfo) -> str | None:
    d = event.get("date")
    if isinstance(d, str) and d.strip():
        return d.strip()[:10]

    ts = event.get("timestamp")
    if isinstance(ts, str):
        dt_utc = _parse_ts_utc(ts)
        if dt_utc is None:
            return None
        return dt_utc.astimezone(tz).date().isoformat()
    return None


def append_event(
    path: Path,
    event: dict,
    *,
    required_fields: tuple[str, ...] = (),
    drop_null: bool = False,
) -> None:
    """
    Append-only write to a log file.

    Constraints:
    - No de-duplication. Always writes one new line at the end of file.
    - If drop_null=True, keys with None values are removed before writing.
    - required_fields are validated as present:
      - for date/source/timestamp: must be non-empty strings
      - for other fields: must not be None
    """
    if not isinstance(event, dict):
        raise ValueError("event must be a dict")

    for f in required_fields:
        v = event.get(f)
        if f in {"date", "source", "timestamp"}:
            if not (isinstance(v, str) and v.strip()):
                raise ValueError(f"event missing required field: {f}")
        else:
            if v is None:
                raise ValueError(f"event missing required field: {f}")

    cleaned: dict[str, Any] = {}
    for k, v in event.items():
        if drop_null and v is None:
            continue
        cleaned[k] = v

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(cleaned, ensure_ascii=False) + "\n")


def write_metrics_event(path: Path, metrics: dict) -> None:
    """
    Append-only write for metrics events.

    Constraints:
    - Required fields: date/source/timestamp (non-empty strings)
    - Null values are removed before writing (None keys are dropped)
    - Always appends to file tail (no overwrite, no de-dup)
    """
    if not isinstance(metrics, dict):
        raise ValueError("metrics must be a dict")

    date = metrics.get("date")
    source = metrics.get("source")
    timestamp = metrics.get("timestamp")
    if not (isinstance(date, str) and date.strip()):
        raise ValueError("metrics missing required field: date")
    if not (isinstance(source, str) and source.strip()):
        raise ValueError("metrics missing required field: source")
    if not (isinstance(timestamp, str) and timestamp.strip()):
        raise ValueError("metrics missing required field: timestamp")

    cleaned: dict[str, Any] = {
        "date": date.strip()[:10],
        "source": source.strip(),
        "timestamp": timestamp.strip(),
    }
    for k, v in metrics.items():
        if k in {"date", "source", "timestamp"}:
            continue
        if v is None:
            continue
        cleaned[k] = v

    append_event(path, cleaned, required_fields=("date", "source", "timestamp"), drop_null=False)


def write_profile_changelog_event(path: Path, event: dict) -> None:
    """
    Append-only write for profile change audit events.

    Constraints:
    - Required fields: timestamp/yaml_path/reason/source
    - Always appends to file tail (no overwrite, no de-dup)
    """
    append_event(
        path,
        event,
        required_fields=("timestamp", "yaml_path", "reason", "source"),
        drop_null=False,
    )


def read_metrics_grouped_by_date(
    path: Path,
    *,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    tz: ZoneInfo | None = None,
) -> list[dict]:
    """
    Read metrics events within a local date range, merge by date, and return a list sorted from old to new.

    Constraints:
    - Input is an append-only event log (one JSON object per line).
    - Each raw event must include timestamp; date may be missing and will be derived from timestamp + tz.
    - Before merging, None fields are removed from each raw event (legacy compatibility).
    - Output groups by date. For the same date+field, the value from the newest timestamp wins.
    """
    if not path.exists():
        return []

    tz = tz or load_profile_timezone()

    by_date: dict[str, dict[str, Any]] = {}
    by_date_latest_ts: dict[str, datetime.datetime] = {}
    by_date_field_ts: dict[str, dict[str, datetime.datetime]] = {}

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not (line or "").strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict):
                continue

            event = {k: v for k, v in raw.items() if v is not None}

            date_s = _event_local_date(event, tz)
            if not date_s:
                continue
            try:
                d = datetime.date.fromisoformat(date_s)
            except ValueError:
                continue
            if start_date and d < start_date:
                continue
            if end_date and d > end_date:
                continue

            ts_raw = event.get("timestamp")
            if not isinstance(ts_raw, str) or not ts_raw.strip():
                continue
            ts_dt = _parse_ts_utc(ts_raw)
            if ts_dt is None:
                continue

            dst = by_date.get(date_s)
            if dst is None:
                dst = {"date": date_s}
                by_date[date_s] = dst
                by_date_field_ts[date_s] = {}

            prev_latest = by_date_latest_ts.get(date_s)
            if prev_latest is None or ts_dt > prev_latest:
                by_date_latest_ts[date_s] = ts_dt
                dst["timestamp"] = ts_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")

            field_ts = by_date_field_ts[date_s]
            for k, v in event.items():
                if k in {"date", "source", "timestamp"}:
                    continue
                if v is None:
                    continue
                prev_f_ts = field_ts.get(k)
                if prev_f_ts is None or ts_dt >= prev_f_ts:
                    field_ts[k] = ts_dt
                    dst[k] = v

    dates = sorted(by_date.keys())
    return [by_date[d] for d in dates]

