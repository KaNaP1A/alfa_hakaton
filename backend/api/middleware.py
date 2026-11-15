import logging
import threading
import time
import uuid
from collections import OrderedDict, deque

from fastapi import FastAPI, Request
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from api.errors import error_response
from config.settings import Settings

logger = logging.getLogger("uvicorn.error")


def install_middleware(app: FastAPI, settings: Settings) -> None:
    buckets: OrderedDict[str, deque[float]] = OrderedDict()
    bucket_lock = threading.Lock()

    @app.middleware("http")
    async def request_limits(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = str(uuid.uuid4())
        started = time.monotonic()
        address = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with bucket_lock:
            bucket = buckets.setdefault(address, deque())
            buckets.move_to_end(address)
            while bucket and bucket[0] <= now - 60:
                bucket.popleft()
            limited = len(bucket) >= settings.requests_per_minute
            if not limited:
                bucket.append(now)
            while len(buckets) > 10000:
                buckets.popitem(last=False)
        response: Response
        if limited:
            response = error_response(
                429, "rate_limited", "Too many requests", headers={"Retry-After": "60"}
            )
        else:
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 32768:
                    break
            if len(body) > 32768:
                response = error_response(413, "body_too_large", "Request body too large")
            else:
                request._body = bytes(body)
                response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        route = request.scope.get("route")
        logger.info(
            "request=%s route=%s status=%d duration_ms=%.1f",
            request_id,
            getattr(route, "path", "unmatched"),
            response.status_code,
            (time.monotonic() - started) * 1000,
        )
        return response
