"""The org works in one timezone (Asia/Kolkata by default); everything is stored in UTC."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from ..config import get_settings

TZ = ZoneInfo(get_settings().timezone)


def now() -> datetime:
    return datetime.now(timezone.utc)


def local(dt: datetime) -> datetime:
    return dt.astimezone(TZ)


def today() -> date:
    return now().astimezone(TZ).date()


def at(day: date, hour: int, minute: int = 0) -> datetime:
    """A local wall-clock time on `day`, returned in UTC."""
    return datetime.combine(day, time(hour, minute), TZ).astimezone(timezone.utc)


def day_bounds(day: date) -> tuple[datetime, datetime]:
    return at(day, 0), at(day + timedelta(days=1), 0)


def workday(day: date) -> bool:
    return day.weekday() < 5


def is_after_hours(dt: datetime) -> bool:
    h = local(dt).hour
    return h >= 21 or h < 6


def fmt_minutes(m: int) -> str:
    h, mm = divmod(int(m), 60)
    return f"{h} h {mm} m" if h and mm else (f"{h} h" if h else f"{mm} m")
