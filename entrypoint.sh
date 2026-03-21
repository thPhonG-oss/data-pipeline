#!/bin/bash
set -e  # Dừng ngay nếu có lệnh nào fail

echo "================================================"
echo "  Stock Pipeline — Starting"
echo "================================================"

# ── Bước 1: Cài vnstock sponsor package nếu có API key ───────────
INSTALLER_FLAG="/app/logs/.vnstock_installed"  # Nằm trong volume mount → tồn tại qua rebuild

if [ -z "$VNSTOCK_API_KEY" ]; then
    echo "⚠️  VNSTOCK_API_KEY not set — running with base vnstock only"
else
    # Chỉ chạy installer một lần duy nhất
    # Flag file đảm bảo restart container không cài lại
    VNSTOCK_SITE="/root/.venv/lib/python3.12/site-packages"
    if [ ! -f "$INSTALLER_FLAG" ] || [ ! -d "$VNSTOCK_SITE" ]; then
        echo "✓ Installing vnstock sponsor packages..."
        /app/vnstock-cli-installer.run -- --api-key "$VNSTOCK_API_KEY"
        touch "$INSTALLER_FLAG"
        echo "✓ Sponsor packages installed"
    else
        echo "✓ Sponsor packages already installed — skipping"
    fi

    # Installer tạo venv riêng tại /root/.venv — expose site-packages cho /opt/venv
    # Pipeline dùng /opt/venv (có SQLAlchemy, APScheduler, v.v.)
    # vnstock_data được cài vào /root/.venv → cần thêm vào PYTHONPATH
    if [ -d "$VNSTOCK_SITE" ]; then
        export PYTHONPATH="${VNSTOCK_SITE}:${PYTHONPATH:-}"
        echo "✓ PYTHONPATH updated: vnstock_data packages accessible"
    fi
fi

# ── Bước 2: Kiểm tra kết nối PostgreSQL ──────────────────────────
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

# ── Bước 3: Chạy pipeline ─────────────────────────────────────────
echo "🚀 Starting scheduler..."
exec python3 main.py schedule
