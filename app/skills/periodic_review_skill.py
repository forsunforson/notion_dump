import datetime
from pathlib import Path
from typing import Literal

from app.core.paths import reports_dir
from app.jobs.periodic_review import PeriodicReviewJob
from app.utils.timezone_utils import load_profile_timezone


Period = Literal["current", "previous"]


def _last_day_of_month(year: int, month: int) -> datetime.date:
    if month == 12:
        nxt = datetime.date(year + 1, 1, 1)
    else:
        nxt = datetime.date(year, month + 1, 1)
    return nxt - datetime.timedelta(days=1)


def _parse_ym(s: str) -> tuple[int, int] | None:
    raw = (s or "").strip()
    if len(raw) != 7 or raw[4] != "-":
        return None
    try:
        y = int(raw[:4])
        m = int(raw[5:])
    except Exception:
        return None
    if y < 1900 or y > 2100:
        return None
    if m < 1 or m > 12:
        return None
    return y, m


def _resolve_week_date_range(*, period: Period, today_local: datetime.date) -> tuple[datetime.date, datetime.date]:
    if period == "current":
        start = today_local - datetime.timedelta(days=today_local.isoweekday() - 1)
        end = today_local
        return start, end

    last_sunday = today_local - datetime.timedelta(days=today_local.isoweekday())
    last_monday = last_sunday - datetime.timedelta(days=6)
    return last_monday, last_sunday


def _resolve_month_date_range(
    *, period: Period, today_local: datetime.date, month: str | None
) -> tuple[datetime.date, datetime.date]:
    if month:
        ym = _parse_ym(month)
        if ym is None:
            raise ValueError("invalid month, expected YYYY-MM")
        y, m = ym
        return datetime.date(y, m, 1), _last_day_of_month(y, m)

    if period == "current":
        return today_local.replace(day=1), today_local

    first_day_this_month = today_local.replace(day=1)
    last_day_prev_month = first_day_this_month - datetime.timedelta(days=1)
    first_day_prev_month = last_day_prev_month.replace(day=1)
    return first_day_prev_month, last_day_prev_month


def _report_path(review_type: Literal["weekly", "monthly"], end_date: datetime.date) -> Path:
    return reports_dir() / f"{review_type}_{end_date.isoformat()}.md"


def _parse_iso_date(s: str) -> datetime.date:
    return datetime.date.fromisoformat((s or "").strip()[:10])


def _weekly_range_line(start_date: datetime.date, end_date: datetime.date) -> str:
    return f"周报范围：{start_date.isoformat()} ~ {end_date.isoformat()}"


def _ensure_weekly_range_prefix(content: str, *, start_date: datetime.date, end_date: datetime.date) -> str:
    line = _weekly_range_line(start_date, end_date)
    stripped = (content or "").strip()
    if not stripped:
        return line

    lines = stripped.splitlines()
    if lines and lines[0].startswith("周报范围："):
        body = "\n".join(lines[1:]).lstrip("\n")
        return f"{line}\n\n{body}".strip()
    return f"{line}\n\n{stripped}".strip()


async def generate_weekly_review(
    *,
    period: Period = "current",
    start_date: str | None = None,
    end_date: str | None = None,
    force_regenerate: bool = False,
) -> str:
    tz = load_profile_timezone()
    today_local = datetime.datetime.now(tz).date()
    if start_date and end_date:
        start_d = _parse_iso_date(start_date)
        end_d = _parse_iso_date(end_date)
    else:
        start_d, end_d = _resolve_week_date_range(period=period, today_local=today_local)

    p = _report_path("weekly", end_d)
    if p.exists() and not force_regenerate:
        content = p.read_text(encoding="utf-8")
        normalized = _ensure_weekly_range_prefix(content, start_date=start_d, end_date=end_d)
        if normalized != (content or "").strip():
            p.write_text(normalized + "\n", encoding="utf-8")
        return normalized

    job = PeriodicReviewJob(review_type="weekly")
    return _ensure_weekly_range_prefix(
        await job.run(start_date=start_d, end_date=end_d),
        start_date=start_d,
        end_date=end_d,
    )


async def generate_monthly_review(
    *,
    period: Period = "current",
    month: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    force_regenerate: bool = False,
) -> str:
    tz = load_profile_timezone()
    today_local = datetime.datetime.now(tz).date()
    if start_date and end_date:
        start_d = _parse_iso_date(start_date)
        end_d = _parse_iso_date(end_date)
    else:
        start_d, end_d = _resolve_month_date_range(period=period, today_local=today_local, month=month)

    p = _report_path("monthly", end_d)
    if p.exists() and not force_regenerate:
        return p.read_text(encoding="utf-8").strip()

    job = PeriodicReviewJob(review_type="monthly")
    return (await job.run(start_date=start_d, end_date=end_d)).strip()


GENERATE_WEEKLY_REVIEW_SCHEMA = {
    "type": "function",
    "function": {
        "name": "generate_weekly_review",
        "description": "Generate a weekly review report for a given local time range and save it under _reports/. If dates are omitted, callers can choose current week (Monday to today) or previous full week (Monday to Sunday).",
        "parameters": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["current", "previous"],
                    "description": "Which week to generate if start_date/end_date are not provided: current means Monday to today, previous means the previous full Monday-Sunday week. Default: current.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Local date start (YYYY-MM-DD). If provided with end_date, overrides period.",
                },
                "end_date": {
                    "type": "string",
                    "description": "Local date end (YYYY-MM-DD, inclusive). If provided with start_date, overrides period.",
                },
                "force_regenerate": {
                    "type": "boolean",
                    "description": "If true, regenerate via LLM even if the report file already exists.",
                }
            },
        },
    },
}


GENERATE_MONTHLY_REVIEW_SCHEMA = {
    "type": "function",
    "function": {
        "name": "generate_monthly_review",
        "description": "Generate a monthly review report for a given local time range and save it under _reports/.",
        "parameters": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["current", "previous"],
                    "description": "Which month to generate if month/start_date/end_date are not provided. Default: current.",
                },
                "month": {
                    "type": "string",
                    "description": "Target month (YYYY-MM). If provided, generates the full month and overrides period.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Local date start (YYYY-MM-DD). If provided with end_date, overrides period/month.",
                },
                "end_date": {
                    "type": "string",
                    "description": "Local date end (YYYY-MM-DD, inclusive). If provided with start_date, overrides period/month.",
                },
                "force_regenerate": {
                    "type": "boolean",
                    "description": "If true, regenerate via LLM even if the report file already exists.",
                }
            },
        },
    },
}
