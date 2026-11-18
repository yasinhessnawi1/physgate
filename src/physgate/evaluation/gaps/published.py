"""The gap trend, published for the Evidence page: stubbed until its rows are red."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from physgate.evaluation.gaps.measure import GapWeek, RoleName
from physgate.evaluation.gaps.vector import GapsError

__all__ = ["ROLES", "GapsError", "PublishedTrend", "publish_trend", "published_name"]

ROLES: tuple[RoleName, ...] = ("control", "firmware")


class PublishedTrend(BaseModel):
    """A stub."""

    model_config = ConfigDict(frozen=True)

    format: Literal[1]
    role: RoleName
    read_at: AwareDatetime
    weeks: tuple[GapWeek, ...] | None
    refused: dict[str, str] | None


def published_name(role: str) -> str:
    """A stub."""
    return f"gap-trend-{role}.json"


def publish_trend(
    trend: Path, *, store: Path, role: RoleName, out: Path, now: datetime | None = None
) -> Path:
    """A stub: writes a trend of no week, read from nothing."""
    path = Path(out) / published_name(role)
    record = PublishedTrend(
        format=1, role=role, read_at=now or datetime.now().astimezone(), weeks=(), refused=None
    )
    path.write_text(record.model_dump_json())
    return path


def read_published(data: bytes, role: str) -> PublishedTrend:
    """A stub."""
    return PublishedTrend.model_validate_json(data)
