"""The error envelope (spec §5). Every 4xx/5xx is raised as an ApiError."""


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.status = status
        self.code = code
        self.message = message or code.replace("_", " ")

    def envelope(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


def malformed(message: str = "request body is not valid JSON of the expected shape") -> ApiError:
    return ApiError(400, "malformed_request", message)


def validation(message: str = "validation failed") -> ApiError:
    return ApiError(422, "validation_failed", message)


def unauthenticated(message: str = "missing or invalid bearer token") -> ApiError:
    return ApiError(401, "unauthenticated", message)


def forbidden(message: str = "not permitted") -> ApiError:
    return ApiError(403, "forbidden", message)


def not_found(message: str = "not found") -> ApiError:
    return ApiError(404, "not_found", message)


def conflict(code: str, message: str = "") -> ApiError:
    return ApiError(409, code, message)


def unprocessable(code: str, message: str = "") -> ApiError:
    return ApiError(422, code, message)
