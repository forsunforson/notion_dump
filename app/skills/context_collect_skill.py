import json
import datetime
import re
from typing import Any

from app.services.context_fetcher import ContextFetcher
from app.utils.timezone_utils import load_profile_timezone


def collect_markdown_context(
    *,
    filters: dict[str, dict],
    start_date: str | None = None,
    end_date: str | None = None,
    days: int | None = None,
    max_items_per_filter: int = 20,
    max_chars_per_item: int = 2000,
) -> str:
    tz = load_profile_timezone()
    today_local = datetime.datetime.now(tz).date()

    if days is not None:
        d = int(days)
        if d <= 0:
            return json.dumps({"error": "days must be > 0"}, ensure_ascii=False)
        end_d = today_local
        start_d = end_d - datetime.timedelta(days=d - 1)
    else:
        if not start_date or not end_date:
            return json.dumps({"error": "start_date and end_date are required if days is not provided"}, ensure_ascii=False)
        try:
            start_d = datetime.date.fromisoformat(str(start_date).strip()[:10])
            end_d = datetime.date.fromisoformat(str(end_date).strip()[:10])
        except Exception:
            return json.dumps({"error": "invalid start_date/end_date, expected YYYY-MM-DD"}, ensure_ascii=False)
        if start_d > end_d:
            return json.dumps({"error": "start_date must be <= end_date"}, ensure_ascii=False)

    start_local = datetime.datetime.combine(start_d, datetime.time.min).replace(tzinfo=tz)
    end_local_exclusive = datetime.datetime.combine(end_d + datetime.timedelta(days=1), datetime.time.min).replace(
        tzinfo=tz
    )
    start_utc = start_local.astimezone(datetime.timezone.utc)
    end_utc = end_local_exclusive.astimezone(datetime.timezone.utc)

    cf = ContextFetcher()

    def created_in_range(raw: str) -> bool:
        meta = cf.parse_frontmatter(raw or "")
        if not meta:
            return False
        created_utc = cf._parse_created_time_utc(meta)
        if not created_utc:
            return False
        return start_utc <= created_utc < end_utc

    compiled_filters: dict[str, Any] = {}
    for name, spec in (filters or {}).items():
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(spec, dict):
            continue
        t = (spec.get("type") or "").strip().lower()
        if t == "daily_entry":
            compiled_filters[name] = cf.make_daily_entry_filter(start_utc=start_utc, end_utc=end_utc)
            continue
        if t == "trade_log":
            compiled_filters[name] = cf.make_trade_log_filter(start_utc=start_utc, end_utc=end_utc)
            continue
        if t == "book_review":
            compiled_filters[name] = cf.make_book_review_filter(start_utc=start_utc, end_utc=end_utc)
            continue
        if t == "movie_review":
            compiled_filters[name] = cf.make_movie_review_filter(start_utc=start_utc, end_utc=end_utc)
            continue
        if t == "contains":
            needle = spec.get("needle")
            if not isinstance(needle, str) or not needle.strip():
                continue
            ci = bool(spec.get("case_insensitive", True))
            n = needle.strip()
            n2 = n.lower()

            def _f(raw: str, *, _n=n, _n2=n2, _ci=ci) -> bool:
                if not created_in_range(raw):
                    return False
                hay = raw or ""
                return (_n2 in hay.lower()) if _ci else (_n in hay)

            compiled_filters[name] = _f
            continue
        if t == "regex":
            pattern = spec.get("pattern")
            if not isinstance(pattern, str) or not pattern.strip():
                continue
            ci = bool(spec.get("case_insensitive", True))
            try:
                rx = re.compile(pattern, flags=re.IGNORECASE if ci else 0)
            except Exception:
                continue

            def _f(raw: str, *, _rx=rx) -> bool:
                if not created_in_range(raw):
                    return False
                return _rx.search(raw or "") is not None

            compiled_filters[name] = _f
            continue

    md_count, buckets = cf.collect_markdown_by_filters(filters=compiled_filters)

    def truncate_body(s: str) -> str:
        if not isinstance(s, str):
            return ""
        if max_chars_per_item is not None and int(max_chars_per_item) > 0 and len(s) > int(max_chars_per_item):
            return s[: int(max_chars_per_item)].rstrip() + "\n(…截断)"
        return s

    out_filters: dict[str, Any] = {}
    for name, items in (buckets or {}).items():
        entries = []
        for it in items or []:
            raw = (it or {}).get("raw") or ""
            path = (it or {}).get("path") or ""
            e = cf.build_entry(raw=raw, path=path, include_path=True)
            if not e:
                continue
            e2 = {
                "created_utc": e["created_utc"].isoformat().replace("+00:00", "Z"),
                "local_date": e.get("local_date") or "",
                "title": e.get("title") or "",
                "path": e.get("path") or "",
                "body": truncate_body(e.get("body") or ""),
            }
            entries.append(e2)
        entries.sort(key=lambda x: x.get("created_utc") or "")

        omitted = 0
        max_n = int(max_items_per_filter) if max_items_per_filter is not None else 20
        if max_n > 0 and len(entries) > max_n:
            keep_head = max_n // 2
            keep_tail = max_n - keep_head
            omitted = len(entries) - (keep_head + keep_tail)
            entries = [*entries[:keep_head], {"omitted": omitted}, *entries[-keep_tail:]]

        out_filters[name] = {"count": len(items or []), "omitted": omitted, "entries": entries}

    payload = {
        "meta": {
            "timezone": tz.key,
            "start_date": start_d.isoformat(),
            "end_date": end_d.isoformat(),
            "md_scanned": md_count,
        },
        "filters": out_filters,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


COLLECT_MARKDOWN_CONTEXT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "collect_markdown_context",
        "description": "Collect local markdown diary/trade logs in a time range using named filters, for later analysis.",
        "parameters": {
            "type": "object",
            "properties": {
                "filters": {
                    "type": "object",
                    "description": "Mapping: filter_name -> filter spec. Each spec has a type and optional parameters.",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": [
                                    "daily_entry",
                                    "trade_log",
                                    "book_review",
                                    "movie_review",
                                    "contains",
                                    "regex",
                                ],
                            },
                            "needle": {"type": "string"},
                            "pattern": {"type": "string"},
                            "case_insensitive": {"type": "boolean"},
                        },
                        "required": ["type"],
                    },
                },
                "start_date": {
                    "type": "string",
                    "description": "Local date start (YYYY-MM-DD). Required if days is not provided.",
                },
                "end_date": {
                    "type": "string",
                    "description": "Local date end (YYYY-MM-DD, inclusive). Required if days is not provided.",
                },
                "days": {
                    "type": "integer",
                    "description": "If provided, collect last N days ending today (local timezone).",
                },
                "max_items_per_filter": {"type": "integer"},
                "max_chars_per_item": {"type": "integer"},
            },
            "required": ["filters"],
        },
    },
}
