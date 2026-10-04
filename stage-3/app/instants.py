"""Instants (stage 3; plan S3-D1).

An input instant is RFC 3339 with an offset. Its comparison key is the exact number of seconds
since the Unix epoch as a Decimal: no rounding, any number of fractional digits, every offset.
Server-assigned instants come from one service-wide monotonic clock with microsecond precision,
so they are unique and strictly increasing.
"""
import re
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from functools import lru_cache

RFC3339_RE = re.compile(r"\A(\d{4})-(\d\d)-(\d\d)[Tt](\d\d):(\d\d):(\d\d)(?:\.(\d+))?"
                        r"([Zz]|[+-]\d\d:\d\d)\Z")
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
NEG_INF = Decimal("-Infinity")
MAX_FRACTION_DIGITS = 9  # D-42: 1..9 fractional digits
ONE_SECOND = timedelta(seconds=1)


def _offset(text: str):
    if text in ("Z", "z"):
        return timezone.utc
    sign = -1 if text[0] == "-" else 1
    return timezone(sign * timedelta(hours=int(text[1:3]), minutes=int(text[4:6])))


@lru_cache(maxsize=1 << 17)
def key(value):
    """Exact seconds since the epoch (Decimal) for an RFC 3339 instant with offset, else None."""
    if not isinstance(value, str):
        return None
    m = RFC3339_RE.match(value)
    if not m:
        return None
    year, month, day, hour, minute, second, fraction, offset = m.groups()
    if fraction and len(fraction) > MAX_FRACTION_DIGITS:
        return None
    try:
        moment = datetime(int(year), int(month), int(day), int(hour), int(minute), int(second),
                          tzinfo=_offset(offset))
        whole = (moment - EPOCH) // ONE_SECOND
    except (ValueError, OverflowError):
        return None
    with localcontext() as ctx:
        ctx.prec = 80
        return Decimal(whole) + (Decimal("0." + fraction) if fraction else Decimal(0))


def repair_query_instant(value):
    """D-42: in a query string an unencoded '+' decodes to a space; a value whose only defect is
    one space right before a trailing HH:MM offset is read as +HH:MM. The echo keeps `value`."""
    if isinstance(value, str) and len(value) > 6 and value[-6] == " " \
            and key(value) is None and key(value[:-6] + "+" + value[-5:]) is not None:
        return value[:-6] + "+" + value[-5:]
    return value


def key_or_min(value) -> Decimal:
    k = key(value)
    return k if k is not None else NEG_INF


def parse(value):
    """datetime (aware, microseconds truncated) for an RFC 3339 instant with offset, else None."""
    if key(value) is None:
        return None
    m = RFC3339_RE.match(value)
    year, month, day, hour, minute, second, fraction, offset = m.groups()
    micro = int((fraction or "0")[:6].ljust(6, "0"))
    return datetime(int(year), int(month), int(day), int(hour), int(minute), int(second),
                    micro, tzinfo=_offset(offset))


def from_micros(us: int) -> str:
    return (EPOCH + timedelta(microseconds=us)).isoformat(timespec="microseconds")


def key_of_micros(us: int) -> Decimal:
    return Decimal(us) / Decimal(1_000_000)


def micros_floor(k: Decimal) -> int:
    with localcontext() as ctx:
        ctx.prec = 80
        return int((k * 1_000_000).to_integral_value(rounding="ROUND_FLOOR"))


class Clock:
    """Service-wide monotonic clock: every tick is later than every earlier tick (by >= 1 µs)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.last_us = 0

    def tick(self, wall_seconds: float) -> str:
        with self._lock:
            self.last_us = max(int(wall_seconds * 1_000_000), self.last_us + 1)
            return from_micros(self.last_us)

    def advance_past(self, k) -> None:
        """Make the next tick later than instant key k (after a reset or an import)."""
        if k is None or k == NEG_INF:
            return
        with self._lock:
            self.last_us = max(self.last_us, micros_floor(k))
