FROM cloudflare/cloudflared:latest AS cloudflared

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt

COPY --from=cloudflared /usr/local/bin/cloudflared /usr/local/bin/cloudflared
COPY songshare ./songshare

ENV SONGSHARE_HOST=0.0.0.0
ENV SONGSHARE_PORT=8080
ENV SONGSHARE_DATA_DIR=/data

EXPOSE 8080
VOLUME ["/data"]

CMD ["python", "-m", "songshare"]
