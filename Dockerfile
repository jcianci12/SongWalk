FROM cloudflare/cloudflared:latest AS cloudflared

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt

COPY --from=cloudflared /usr/local/bin/cloudflared /usr/local/bin/cloudflared
COPY songwalk ./songwalk

ENV SONGWALK_HOST=0.0.0.0
ENV SONGWALK_PORT=8080
ENV SONGWALK_DATA_DIR=/data

EXPOSE 8080
VOLUME ["/data"]

CMD ["python", "-m", "songwalk"]
