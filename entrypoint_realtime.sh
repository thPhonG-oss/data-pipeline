#!/bin/bash
set -e

echo "================================================"
echo "  Real-time Pipeline — Starting"
echo "================================================"

# Không cài vnstock — realtime modules chỉ dùng paho-mqtt, redis, sqlalchemy

# ── Kiểm tra kết nối PostgreSQL ──────────────────────────────────
echo "⏳ Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT:-5432}..."
until python3 -c "
import psycopg2, os, sys
try:
    psycopg2.connect(
        host=os.environ['DB_HOST'],
        port=os.environ.get('DB_PORT', 5432),
        dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
    )
    sys.exit(0)
except Exception:
    sys.exit(1)
"; do
    echo "  PostgreSQL not ready — retrying in 3s..."
    sleep 3
done
echo "✅ PostgreSQL is ready"

# ── Chạy lệnh được truyền vào (subscriber hoặc processor) ─────────
echo "🚀 Starting: $*"
exec "$@"
