"""Unified API errors (body matches {code, message, data})."""


class ApiError(Exception):
    def __init__(self, code: int, message: str, http_status: int = 200) -> None:
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)
