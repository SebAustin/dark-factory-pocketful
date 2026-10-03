"""Request context, JSON parsing and response writing."""
import json
import operator
import re
from decimal import Decimal
from itertools import accumulate, count
from urllib.parse import parse_qsl, urlsplit

from . import errors

CONTENT_TYPE = "application/json; charset=utf-8"


MAX_DEPTH = 512           # nesting deeper than this is refused before json.loads sees it
MAX_INT_DIGITS = 4000     # below Python's int-from-str limit; longer integers stay Decimal
_STRING_RE = re.compile(rb'"(?:[^"\\]++|\\.)*+"')
_NOT_BRACKETS = bytes(b for b in range(256) if b not in b"[]{}")
_DEPTH_STEP = bytes.maketrans(b"[]{}", b"\x02\x00\x02\x00")


def _reject_constant(name: str):
    raise ValueError("non-finite number " + name)


def _parse_int(text: str):
    return int(text) if len(text) <= MAX_INT_DIGITS else Decimal(text)


def _too_deep(raw: bytes) -> bool:
    """Max nesting depth of [ and { outside strings, in C-speed passes (no Python per byte
    loop over string contents). Depth after k brackets = (sum of steps) - k, steps 2 or 0."""
    brackets = _STRING_RE.sub(b"", raw).translate(None, _NOT_BRACKETS)
    if len(brackets) <= MAX_DEPTH:
        return False
    steps = brackets.translate(_DEPTH_STEP)
    return max(map(operator.sub, accumulate(steps), count(1))) > MAX_DEPTH


def _has_lone_surrogate(raw: bytes, value) -> bool:
    # Raw UTF-8 cannot carry a surrogate (decode fails), so only \\uD800-\\uDFFF escapes can.
    if b"\\ud" not in raw.lower():
        return False
    try:
        json.dumps(value, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        return True
    return False


def parse_json(raw: bytes):
    """Parse a body. Floats and very long integers become Decimal so integrality and bounds
    are judged exactly without ever building a huge int. Refuses deep nesting and lone
    surrogates (which could never be written back out as UTF-8) with 400."""
    if _too_deep(raw):
        raise errors.malformed("body nests too deeply")
    try:
        text = raw.decode("utf-8")
        value = json.loads(text, parse_float=Decimal, parse_int=_parse_int,
                           parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise errors.malformed("body is not valid JSON") from exc
    if _has_lone_surrogate(raw, value):
        raise errors.malformed("body contains an unpaired UTF-16 surrogate")
    return value


class Ctx:
    def __init__(self, method: str, target: str, headers, raw_body: bytes) -> None:
        parts = urlsplit(target)
        self.method = method
        self.path = parts.path
        self.query = dict(parse_qsl(parts.query, keep_blank_values=True))
        self.headers = headers
        self.raw_body = raw_body
        self.params: dict = {}
        self._parsed = None

    def preparse(self) -> None:
        """Parse the body once, outside any lock; keep the value or the error for later."""
        if self._parsed is not None:
            return
        if not self.raw_body.strip():
            self._parsed = ("empty", None)
            return
        try:
            self._parsed = ("ok", parse_json(self.raw_body))
        except errors.ApiError as err:
            self._parsed = ("error", err)

    def json_object(self, empty_ok: bool = False) -> dict:
        self.preparse()
        kind, value = self._parsed
        if kind == "empty":
            if empty_ok:
                return {}
            raise errors.malformed("body is not valid JSON")
        if kind == "error":
            raise value
        if not isinstance(value, dict):
            raise errors.malformed("body must be a JSON object")
        return value

    def header(self, name: str):
        return self.headers.get(name)

    def bearer_token(self):
        value = self.headers.get("Authorization")
        if not value:
            return None
        scheme, _, token = value.strip().partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token:
            return None
        return token


def encode(obj) -> bytes:
    try:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except UnicodeEncodeError:  # defence in depth: escape rather than fail to answer
        return json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("ascii")
