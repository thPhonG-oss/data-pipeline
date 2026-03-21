"""Kiểm tra kết quả smoke test real-time pipeline."""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import redis
from sqlalchemy import text
from config.settings import settings
from db.connection import engine

print("=" * 60)
print("REAL-TIME PIPELINE — SMOKE TEST CHECK")
print("=" * 60)

# 1. Redis streams
r = redis.Redis(host=settings.redis_host, port=settings.redis_port, decode_responses=True)
try:
    ping = r.ping()
    len_1m = r.xlen("stream:ohlc:1m") if r.exists("stream:ohlc:1m") else 0
    len_5m = r.xlen("stream:ohlc:5m") if r.exists("stream:ohlc:5m") else 0
    print(f"\n[Redis]")
    print(f"  stream:ohlc:1m  : {len_1m:,} messages")
    print(f"  stream:ohlc:5m  : {len_5m:,} messages")
except Exception as e:
    print(f"[Redis] ERROR: {e}")

# 2. PostgreSQL price_intraday
try:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT symbol, resolution, COUNT(*) as candles,
                   MIN(time) as first_candle, MAX(time) as last_candle
            FROM price_intraday
            GROUP BY symbol, resolution
            ORDER BY symbol, resolution
        """)).fetchall()

    print(f"\n[PostgreSQL] price_intraday — {len(rows)} symbol/resolution combos")
    if rows:
        print(f"  {'Symbol':<8} {'Res':>4} {'Candles':>8}  {'First':>22}  {'Last':>22}")
        print(f"  {'-'*8} {'-'*4} {'-'*8}  {'-'*22}  {'-'*22}")
        for r in rows:
            print(f"  {r[0]:<8} {r[1]:>4} {r[2]:>8}  {str(r[3])[:22]:>22}  {str(r[4])[:22]:>22}")
    else:
        print("  (no data yet — run subscriber during trading hours)")
except Exception as e:
    print(f"[PostgreSQL] ERROR: {e}")

print("\n" + "=" * 60)
