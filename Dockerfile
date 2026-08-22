# syntax=docker/dockerfile:1

# Build stage: 컴파일이 필요한 패키지는 여기서 빌드한다(gcc 등 빌드 도구체인).
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --prefix=/install -r requirements.txt

# Runtime stage: 빌드 산출물만 복사, gcc/빌드 의존성은 런타임 이미지에 남기지 않는다.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/usr/local/bin:/usr/local/sbin:$PATH" \
    PYTHONPATH="/install/lib/python3.12/site-packages:/app"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /install

COPY . .

RUN mkdir -p /app/data /app/uploads /app/static /app/logs && \
    groupadd -r writ && useradd -r -g writ -d /app -s /sbin/nologin writ && \
    chown -R writ:writ /app

USER writ

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/server-info', timeout=4)" || exit 1

RUN chmod +x start.sh
CMD ["./start.sh"]