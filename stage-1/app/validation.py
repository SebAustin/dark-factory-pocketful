"""Field rules shared by every endpoint (spec §4, §5). One rule per function."""
import re
from decimal import Decimal

from . import errors

HANDLE_RE = re.compile(r"^[a-z0-9_]{1,20}$")
DIGITS_RE = re.compile(r"^[0-9]+$")
MAX_AMOUNT = 1_000_000_000
MAX_NOTE = 200
MAX_ID = 64
MAX_KEY = 255
BALANCE_LIMIT = 2 ** 53
VISIBILITIES = ("public", "private")


def integral(value):
    """Return the int a JSON number denotes, or None if it is not an integral number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal) and value.is_finite() and value == value.to_integral_value():
        return int(value)
    return None


def amount(value) -> int:
    n = integral(value)
    if n is None or n < 1 or n > MAX_AMOUNT:
        raise errors.validation("amount must be an integer from 1 to 1000000000")
    return n


def note(body: dict, name: str = "note") -> str:
    if name not in body:
        return ""
    value = body[name]
    if not isinstance(value, str):
        raise errors.validation("note must be a string")
    if len(value) > MAX_NOTE:
        raise errors.validation("note must be at most 200 characters")
    return value


def visibility(body: dict) -> str:
    if "visibility" not in body:
        return "public"
    value = body["visibility"]
    if value not in VISIBILITIES or not isinstance(value, str):
        raise errors.validation("visibility must be public or private")
    return value


def req_str(body: dict, name: str) -> str:
    if name not in body:
        raise errors.validation(name + " is required")
    value = body[name]
    if not isinstance(value, str):
        raise errors.malformed(name + " must be a string")
    return value


def handle_value(value: str) -> str:
    if not HANDLE_RE.match(value):
        raise errors.validation("not a valid handle")
    return value


def query_int(query: dict, name: str, default: int, lo: int, hi: int = None) -> int:
    if name not in query:
        return default
    raw = query[name]
    if not DIGITS_RE.match(raw):
        raise errors.validation(name + " must be plain decimal digits")
    n = int(raw)
    if n < lo or (hi is not None and n > hi):
        raise errors.validation(name + " out of range")
    return n


def query_enum(query: dict, name: str, allowed):
    if name not in query:
        return None
    if query[name] not in allowed:
        raise errors.validation(name + " has an unknown value")
    return query[name]


def _canon_value(value):
    if isinstance(value, dict):
        return {k: _canon_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_canon_value(v) for v in value]
    if isinstance(value, Decimal):
        n = integral(value)
        return n if n is not None else {"$decimal": str(value.normalize())}
    return value


def canonical(value) -> str:
    """Canonical text of a parsed JSON value: key order, whitespace and 1000/1000.0/1e3 vanish."""
    import json
    return json.dumps(_canon_value(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)
