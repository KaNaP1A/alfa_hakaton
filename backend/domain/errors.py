"""Application failures, independent of HTTP and persistence libraries."""


class AppError(Exception):
    def __init__(
        self,
        status: int,
        message: str,
        *,
        code: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.message = message
        self.code = code or {
            400: "invalid_request",
            401: "unauthorized",
            404: "not_found",
            409: "conflict",
            422: "validation_error",
            429: "rate_limited",
            502: "upstream_error",
            503: "unavailable",
            504: "upstream_timeout",
        }.get(status, "internal_error")
        self.headers = headers
        super().__init__(message)


class RepositoryConflict(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(409, message)
