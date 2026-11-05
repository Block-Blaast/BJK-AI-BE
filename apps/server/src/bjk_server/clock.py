"""시간 기준. 화면·업무 날짜는 Asia/Seoul, 저장은 timezone 포함 시각."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def utcnow() -> datetime:
    return datetime.now(UTC)
