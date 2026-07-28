FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data /app/uploads /app/static /app/logs && \
    groupadd -r writ && useradd -r -g writ -d /app -s /sbin/nologin writ && \
    chown -R writ:writ /app

USER writ

EXPOSE 8000

RUN chmod +x start.sh
CMD ["./start.sh"]
