import json
import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.utils.timezone_utils import load_profile_timezone


def append_jsonl(path: Path, item: dict) -> None:
    if not isinstance(item, dict):
        raise ValueError("item must be a dict")

    date = item.get("date")
    source = item.get("source")
    timestamp = item.get("timestamp")
    if not (isinstance(date, str) and date.strip()):
        raise ValueError("item missing required field: date")
    if not (isinstance(source, str) and source.strip()):
        raise ValueError("item missing required field: source")
    if not (isinstance(timestamp, str) and timestamp.strip()):
        raise ValueError("item missing required field: timestamp")

    cleaned: dict[str, Any] = {
        "date": date.strip()[:10],
        "source": source.strip(),
        "timestamp": timestamp.strip(),
    }
    for k, v in item.items():
        if k in {"date", "source", "timestamp"}:
            continue
        if v is None:
            continue
        cleaned[k] = v

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(cleaned, ensure_ascii=False) + "\n")


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


def _event_local_date(item: dict, tz: ZoneInfo) -> str | None:
    d = item.get("date")
    if isinstance(d, str) and d.strip():
        return d.strip()[:10]
    ts = item.get("timestamp")
    if isinstance(ts, str):
        dt_utc = _parse_ts_utc(ts)
        if dt_utc is None:
            return None
        return dt_utc.astimezone(tz).date().isoformat()
    return None


def read_jsonl_grouped_by_date(
    path: Path,
    *,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    tz: ZoneInfo | None = None,
) -> list[dict]:
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
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            item = {k: v for k, v in item.items() if v is not None}

            date_s = _event_local_date(item, tz)
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

            ts_raw = item.get("timestamp")
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
            for k, v in item.items():
                if k in {"date", "source"}:
                    continue
                if v is None:
                    continue
                prev_f_ts = field_ts.get(k)
                if prev_f_ts is None or ts_dt >= prev_f_ts:
                    field_ts[k] = ts_dt
                    dst[k] = v

    dates = sorted(by_date.keys())
    return [by_date[d] for d in dates]
