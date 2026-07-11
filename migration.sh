#!/bin/bash
set -e

echo "🐳 Starting database container..."
docker compose up -d db

echo "⏳ Waiting for database to be ready..."
until docker compose exec db pg_isready -U postgres >/dev/null 2>&1; do
  sleep 1
done
echo "✅ Database is ready!"

if [ "$RUN_MIGRATIONS" = "true" ]; then
  echo "🚀 Running database migrations..."
  docker compose run --rm backend alembic upgrade head
fi

docker compose down

echo "✨ Deployment successfully completed!"
