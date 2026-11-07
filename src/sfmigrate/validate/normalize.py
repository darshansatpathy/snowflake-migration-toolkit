"""Turn values from different engines and drivers into comparable ones.

Each rule exists because a real migration produces differences that are not data defects:
CHAR padding (Teradata), '' versus NULL (Oracle), time zones, numeric scale and float noise.
They are off unless configured, so nothing is hidden by default.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field


class Rules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    trim_trailing: bool = Field(default=False, description="Ignore trailing spaces (CHAR padding)")
    empty_as_null: bool = Field(default=False, description="Treat '' as NULL (Oracle semantics)")
    case_insensitive: bool = Field(default=False, description="Compare strings without case")
    numeric_tolerance: float = Field(default=0.0, ge=0, description="Absolute tolerance for numbers")
    timestamp_timezone: str = Field(default="UTC", description="Zone of naive timestamps on this side")
    timestamp_precision: int = Field(default=6, ge=0, le=6, description="Fractional digits compared")
    date_equals_midnight: bool = Field(default=False, description="A DATE equals a timestamp at 00:00:00")

    def merged(self, override: dict[str, Any] | None) -> Rules:
        return self.model_copy(update=override or {})


def value(v: Any, rules: Rules, zone: str | None = None) -> Any:
    if v is None:
        return None
    if isinstance(v, str):
        s = v.rstrip(" ") if rules.trim_trailing else v
        if rules.empty_as_null and s == "":
            return None
        return s.casefold() if rules.case_insensitive else s
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, Decimal)):
        return Decimal(v)
    if isinstance(v, float):
        try:
            return Decimal(repr(v))
        except InvalidOperation:
            return v
    if isinstance(v, dt.datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=ZoneInfo(zone or rules.timestamp_timezone))
        v = v.astimezone(dt.UTC).replace(tzinfo=None)
        drop = 6 - rules.timestamp_precision
        if drop:
            v = v.replace(microsecond=(v.microsecond // 10**drop) * 10**drop)
        return v
    if isinstance(v, dt.date):
        return dt.datetime(v.year, v.month, v.day) if rules.date_equals_midnight else v
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).hex()
    return v


def equal(a: Any, b: Any, rules: Rules) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return abs(a - b) <= Decimal(repr(rules.numeric_tolerance))
    return bool(a == b)


def key(values: tuple[Any, ...]) -> tuple[Any, ...]:
    """Sortable key: None first, then by type name, then value, so mixed types never raise."""
    return tuple((v is not None, type(v).__name__ if not isinstance(v, (int, Decimal)) else "num", v) for v in values)
