#!/bin/bash
set -e  # Dừng ngay nếu có lệnh nào fail

echo "================================================"
echo "  Stock Pipeline — Starting"
echo "================================================"

# ── Bước 1: Thiết lập PYTHONPATH cho vnstock_data (cài tại build time) ──────
# vnstock installer tạo /root/.venv — cần thêm /opt/venv site-packages vào PYTHONPATH
# để /root/.venv/bin/python3 thấy được SQLAlchemy, APScheduler, v.v.
VNSTOCK_SITE="/root/.venv/lib/python3.12/site-packages"
OPT_VENV_SITE="/opt/venv/lib/python3.12/site-packages"

if [ -d "$VNSTOCK_SITE" ]; then
    export PYTHONPATH="${OPT_VENV_SITE}:${PYTHONPATH:-}"
    export PYTHON_BIN="/root/.venv/bin/python3"
    echo "✓ Using /root/.venv python3 + /opt/venv site-packages"
else
    export PYTHON_BIN="python3"
    echo "⚠️  /root/.venv not found — using /opt/venv python3 (vnstock_data may be missing)"
fi

# ── Bước 2: Kiểm tra kết nối PostgreSQL ──────────────────────────
PYTHON_BIN="${PYTHON_BIN:-python3}"
echo "⏳ Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT:-5432}..."
until $PYTHON_BIN -c "
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

# ── Bước 3: Chạy pipeline ─────────────────────────────────────────
echo "🚀 Starting scheduler..."
exec $PYTHON_BIN main.py schedule
