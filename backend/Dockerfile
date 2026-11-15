FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY alfa_backend ./alfa_backend
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps . && useradd --create-home app && chmod -R a+rX /app
USER app
ENV ALFA_DATABASE_URL=sqlite:////home/app/backend.sqlite3
EXPOSE 8080
CMD ["uvicorn", "alfa_backend.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--no-proxy-headers"]
