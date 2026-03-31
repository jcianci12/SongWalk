FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV SONGSHARE_HOST=0.0.0.0
ENV SONGSHARE_PORT=8080
ENV SONGSHARE_DATA_DIR=/data

EXPOSE 8080
VOLUME ["/data"]

CMD ["python", "-m", "songshare"]

