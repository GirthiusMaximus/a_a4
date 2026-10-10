# rustwatch: one image for the API, the watcher loop and the bot.
# No systemd, no supervisor. Compose gives each process its own container and restart policy.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/srv/app:/srv/tools/skinprobe \
    DATA_DIR=/data \
    SKINS_DIR=/skins \
    HOST=0.0.0.0 \
    PORT=8000

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY app/requirements.txt /srv/app/requirements.txt
RUN pip install -r /srv/app/requirements.txt

COPY app /srv/app
COPY tools/skinprobe /srv/tools/skinprobe

# Bind-mounted ./data is owned by whoever cloned the repo. Dropping to a made-up uid here is the
# failure mode where `docker compose up` cannot write its own database on a fresh checkout. This is
# an internal tool; it runs as root in the container on purpose.
RUN mkdir -p /data /skins

EXPOSE 8000
LABEL org.opencontainers.image.title="rustwatch" \
      org.opencontainers.image.description="Rust store rotation watcher, skin IP screener, review queue and Discord outbox"

HEALTHCHECK --interval=30s --timeout=4s --start-period=12s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" || exit 1

CMD ["python", "-m", "rustwatch", "serve"]
