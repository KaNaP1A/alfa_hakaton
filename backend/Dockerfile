FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_NO_DEV=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY alfa_backend ./alfa_backend
RUN uv sync --frozen --no-dev && useradd --create-home app && chmod -R a+rX /app
USER app
ENV ALFA_DATABASE_URL=sqlite:////home/app/backend.sqlite3
EXPOSE 8080
CMD ["/app/.venv/bin/uvicorn", "alfa_backend.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--no-proxy-headers"]
