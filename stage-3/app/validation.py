"""Field rules shared by every endpoint (spec §4, §5). One rule per function."""
import json
import re
from decimal import Decimal

from . import errors

# \A...\Z, not ^...$: "$" would also accept a trailing newline.
HANDLE_RE = re.compile(r"\A[a-z0-9_]{1,20}\Z")
DIGITS_RE = re.compile(r"\A[0-9]+\Z")
MAX_QUERY_DIGITS = 15          # beyond this an integer query value is "very large"
MAX_INTEGRAL_EXPONENT = 18     # |n| < 10**19: covers every bounded field (amount, ±2**53)
MAX_AMOUNT = 1_000_000_000
MAX_NOTE = 200
MAX_ID = 64
MAX_KEY = 255
BALANCE_LIMIT = 2 ** 53
VISIBILITIES = ("public", "private")


def integral(value):
    """Return the int a JSON number denotes, or None if it is not a bounded integral number.

    Never builds a huge int: a Decimal beyond 10**19 in magnitude (e.g. 1e999999999) is None,
    which every caller already treats as invalid, because every numeric field is bounded.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, Decimal) or not value.is_finite():
        return None
    if value.is_zero():
        return 0
    if value.adjusted() > MAX_INTEGRAL_EXPONENT or value.adjusted() < 0:
        return None  # too large, or a nonzero magnitude below 1 (cannot be integral)
    if value != value.to_integral_value():
        return None
    return int(value)


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
    digits = raw.lstrip("0") or "0"
    n = int(digits) if len(digits) <= MAX_QUERY_DIGITS else 10 ** MAX_QUERY_DIGITS
    if n < lo or (hi is not None and n > hi):
        raise errors.validation(name + " out of range")
    return n


def query_enum(query: dict, name: str, allowed):
    if name not in query:
        return None
    if query[name] not in allowed:
        raise errors.validation(name + " has an unknown value")
    return query[name]


def _number_key(value) -> str:
    """Exact text of a JSON number's value, without building big ints or rounding.

    1000, 1000.0, 1e3 and 10000e-1 all give "1e3"; -0 and 0.0 give "0".
    """
    sign, digits, exponent = Decimal(value).as_tuple()
    text = "".join(map(str, digits))
    stripped = text.rstrip("0")
    if not stripped:
        return "0"
    exponent += len(text) - len(stripped)
    return "{}{}e{}".format("-" if sign else "", stripped, exponent)


def canonical(value) -> str:
    """Canonical text of a parsed JSON value: key order, whitespace and 1000/1000.0/1e3 vanish.

    Iterative (no recursion limit) and type-tagged: strings are always quoted, numbers never,
    so true != 1 and "1" != 1. Callers bound nesting depth before parsing.
    """
    out = []
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, _Text):
            out.append(item)
        elif isinstance(item, dict):
            parts = [_Text("{")]
            for i, key in enumerate(sorted(item)):
                if i:
                    parts.append(_Text(","))
                parts.append(_Text(json.dumps(key, ensure_ascii=False) + ":"))
                parts.append(item[key])
            parts.append(_Text("}"))
            stack.extend(reversed(parts))
        elif isinstance(item, list):
            parts = [_Text("[")]
            for i, element in enumerate(item):
                if i:
                    parts.append(_Text(","))
                parts.append(element)
            parts.append(_Text("]"))
            stack.extend(reversed(parts))
        elif item is None or isinstance(item, bool):
            out.append(json.dumps(item))
        elif isinstance(item, str):
            out.append(json.dumps(item, ensure_ascii=False))
        else:
            out.append("n" + _number_key(item))
    return "".join(out)


class _Text(str):
    """A piece of already-rendered canonical text on the work stack."""
