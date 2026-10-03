"""Request context, JSON parsing and response writing."""
import json
from decimal import Decimal
from urllib.parse import parse_qsl, urlsplit

from . import errors

CONTENT_TYPE = "application/json; charset=utf-8"


def _reject_constant(name: str):
    raise ValueError("non-finite number " + name)


def parse_json(raw: bytes):
    """Parse a body; floats become Decimal so integrality is judged exactly."""
    try:
        text = raw.decode("utf-8")
        return json.loads(text, parse_float=Decimal, parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise errors.malformed("body is not valid JSON") from exc


class Ctx:
    def __init__(self, method: str, target: str, headers, raw_body: bytes) -> None:
        parts = urlsplit(target)
        self.method = method
        self.path = parts.path
        self.query = dict(parse_qsl(parts.query, keep_blank_values=True))
        self.headers = headers
        self.raw_body = raw_body
        self.params: dict = {}
        self._body = None

    def json_object(self, empty_ok: bool = False) -> dict:
        if self._body is None:
            if empty_ok and not self.raw_body.strip():
                self._body = {}
            else:
                value = parse_json(self.raw_body)
                if not isinstance(value, dict):
                    raise errors.malformed("body must be a JSON object")
                self._body = value
        return self._body

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
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
