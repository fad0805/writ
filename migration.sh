#!/bin/bash
set -e

CMD="${1:-upgrade}"
MSG="$2"

if [ "$CMD" = "new" ]; then
  if [ -z "$MSG" ]; then
    echo "Usage: $0 new \"description of migration\""
    exit 1
  fi
  echo "🆕 Creating new migration: $MSG"
  docker compose run --rm -T api alembic revision --autogenerate -m "$MSG"
  echo "✅ Migration created! Review the file and run '$0 upgrade' to apply."
  exit 0
fi

echo "🐳 Starting database container..."
docker compose up -d db

echo "⏳ Waiting for database to be ready..."
until docker compose exec db pg_isready -U postgres >/dev/null 2>&1; do
  sleep 1
done
echo "✅ Database is ready!"

echo "🚀 Running database migrations..."
docker compose run --rm -T api alembic upgrade head

docker compose down

echo "✨ Migration completed successfully!"
