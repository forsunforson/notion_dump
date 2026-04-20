import datetime
import asyncio
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.skills import periodic_review_skill as s


class FixedDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime.datetime(2026, 3, 31, 12, 0, 0, tzinfo=tz)


def test_resolve_week_date_range_current(monkeypatch):
    tz = ZoneInfo("Asia/Shanghai")
    monkeypatch.setattr(s, "load_profile_timezone", lambda: tz)
    monkeypatch.setattr(s.datetime, "datetime", FixedDateTime)

    today = FixedDateTime.now(tz).date()
    start_d, end_d = s._resolve_week_date_range(period="current", today_local=today)
    assert end_d == today
    assert start_d.isoweekday() == 1


def test_resolve_week_date_range_previous(monkeypatch):
    tz = ZoneInfo("Asia/Shanghai")
    monkeypatch.setattr(s, "load_profile_timezone", lambda: tz)
    monkeypatch.setattr(s.datetime, "datetime", FixedDateTime)

    today = FixedDateTime.now(tz).date()
    start_d, end_d = s._resolve_week_date_range(period="previous", today_local=today)
    assert start_d.isoweekday() == 1
    assert end_d.isoweekday() == 7
    assert end_d < today


def test_resolve_month_date_range_previous(monkeypatch):
    tz = ZoneInfo("Asia/Shanghai")
    monkeypatch.setattr(s, "load_profile_timezone", lambda: tz)
    monkeypatch.setattr(s.datetime, "datetime", FixedDateTime)

    today = FixedDateTime.now(tz).date()
    start_d, end_d = s._resolve_month_date_range(period="previous", today_local=today, month=None)
    assert start_d == datetime.date(2026, 2, 1)
    assert end_d == datetime.date(2026, 2, 28)


def test_resolve_month_date_range_specific_month(monkeypatch):
    tz = ZoneInfo("Asia/Shanghai")
    monkeypatch.setattr(s, "load_profile_timezone", lambda: tz)
    monkeypatch.setattr(s.datetime, "datetime", FixedDateTime)

    today = FixedDateTime.now(tz).date()
    start_d, end_d = s._resolve_month_date_range(period="current", today_local=today, month="2024-02")
    assert start_d == datetime.date(2024, 2, 1)
    assert end_d == datetime.date(2024, 2, 29)


def test_resolve_month_date_range_invalid_month(monkeypatch):
    tz = ZoneInfo("Asia/Shanghai")
    monkeypatch.setattr(s, "load_profile_timezone", lambda: tz)
    monkeypatch.setattr(s.datetime, "datetime", FixedDateTime)

    today = FixedDateTime.now(tz).date()
    with pytest.raises(ValueError):
        s._resolve_month_date_range(period="current", today_local=today, month="2026-13")


def test_generate_weekly_review_adds_range_prefix_to_cached_report(monkeypatch):
    tz = ZoneInfo("Asia/Shanghai")
    monkeypatch.setattr(s, "load_profile_timezone", lambda: tz)
    monkeypatch.setattr(s.datetime, "datetime", FixedDateTime)

    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setattr(s, "reports_dir", lambda: Path(td))
        report_path = Path(td) / "weekly_2026-03-29.md"
        report_path.write_text("## 1. 冰冷的镜像\n内容", encoding="utf-8")

        result = asyncio.run(s.generate_weekly_review(period="previous"))

        assert result.startswith("周报范围：2026-03-23 ~ 2026-03-29")
        assert report_path.read_text(encoding="utf-8").startswith("周报范围：2026-03-23 ~ 2026-03-29")
