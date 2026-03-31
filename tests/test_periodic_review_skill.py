import datetime
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
