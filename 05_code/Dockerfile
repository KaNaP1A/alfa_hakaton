FROM postgres:17.6-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY src /app/src
ENV PYTHONPATH=/app/src
ENTRYPOINT ["python3", "-m", "alfa_reco"]
