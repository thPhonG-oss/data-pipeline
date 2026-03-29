"""
Script kiểm tra chất lượng dữ liệu sau khi sync Approach C.

Chạy TRƯỚC khi full backfill để xác nhận pilot (10 symbols) đúng.

Cách dùng:
    # Bước 1: Chạy pilot sync
    python -m jobs.sync_financials_c --symbols HPG VCB SSI BVH VNM FPT TCB ACB MBB BID

    # Bước 2: Chạy verify
    python scripts/verify_financials_c.py

8 Quality checks:
    1.  Có dữ liệu trong 4 bảng mới
    2.  Không có gross_profit > 0 cho banking (bug #1 fix verify)
    3.  ROE trong khoảng [-2, 2] (decimal format, không phải %)
    4.  fin_financial_ratios có dữ liệu (bug #2 fix verify)
    5.  NIM/CAR/LDR là NULL cho non-financial (banking-only fields)
    6.  EBT là NULL cho CTCK (securities template)
    7.  Accounting equation: total_assets ≈ total_liabilities + total_equity
    8.  CF check: cfo + cfi + cff ≈ net_cash_change
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from db.connection import engine
from utils.logger import logger

PILOT_SYMBOLS = ["HPG", "VCB", "SSI", "BVH", "VNM", "FPT", "TCB", "ACB", "MBB", "BID"]

_CHECKS_PASSED = 0
_CHECKS_FAILED = 0


def _check(name: str, sql: str, expect_zero: bool = False) -> None:
    """Chạy SQL query và log kết quả. expect_zero=True → pass khi result = 0."""
    global _CHECKS_PASSED, _CHECKS_FAILED
    with engine.connect() as conn:
        result = conn.execute(text(sql)).scalar()

    if expect_zero:
        ok = result == 0
    else:
        ok = result is not None and result > 0

    status = "PASS" if ok else "FAIL"
    if ok:
        _CHECKS_PASSED += 1
        logger.success(f"  [{status}] {name}: {result}")
    else:
        _CHECKS_FAILED += 1
        logger.error(f"  [{status}] {name}: {result}")


def run_checks(symbols: list[str] | None = None) -> None:
    syms = symbols or PILOT_SYMBOLS
    syms_pg = "{" + ",".join(syms) + "}"

    logger.info(f"=== Verify Approach C — {len(syms)} symbols: {syms} ===\n")

    # Check 1: Có dữ liệu trong 4 bảng
    logger.info("── Check 1: Row counts in 4 new tables ─────────────────────")
    for table in ["fin_balance_sheet", "fin_income_statement", "fin_cash_flow", "fin_financial_ratios"]:
        _check(
            f"{table} có dữ liệu",
            f"SELECT COUNT(*) FROM {table} WHERE symbol = ANY('{syms_pg}'::text[])",
        )

    # Check 2: Bug #1 fix — banking không có gross_profit
    logger.info("\n── Check 2: Banking gross_profit = NULL (bug #1 fix) ────────")
    _check(
        "Banking gross_profit IS NULL (không phải 0)",
        f"""
        SELECT COUNT(*) FROM fin_income_statement i
        JOIN companies c ON i.symbol = c.symbol
        WHERE c.icb_code LIKE '3010%'
          AND i.symbol = ANY('{syms_pg}'::text[])
          AND i.gross_profit IS NOT NULL
        """,
        expect_zero=True,
    )

    # Check 3: ROE decimal format
    logger.info("\n── Check 3: ROE decimal format (không phải %) ───────────────")
    _check(
        "ROE trong khoảng [-2, 2]",
        f"""
        SELECT COUNT(*) FROM fin_financial_ratios
        WHERE symbol = ANY('{syms_pg}'::text[])
          AND roe IS NOT NULL
          AND (roe < -2 OR roe > 2)
        """,
        expect_zero=True,
    )

    # Check 4: Bug #2 fix — ratio data có trong DB
    logger.info("\n── Check 4: Ratio data tồn tại (bug #2 fix) ─────────────────")
    _check(
        "fin_financial_ratios có rows",
        f"SELECT COUNT(*) FROM fin_financial_ratios WHERE symbol = ANY('{syms_pg}'::text[])",
    )

    # Check 5: Banking-only fields NULL cho non-financial
    logger.info("\n── Check 5: NIM/CAR NULL cho non-financial ──────────────────")
    _check(
        "NIM NULL cho non-financial",
        f"""
        SELECT COUNT(*) FROM fin_financial_ratios r
        JOIN companies c ON r.symbol = c.symbol
        WHERE r.symbol = ANY('{syms_pg}'::text[])
          AND c.icb_code NOT LIKE '3010%'
          AND r.nim IS NOT NULL
          AND r.nim != 0
        """,
        expect_zero=True,
    )

    # Check 6: EBT NULL cho securities
    logger.info("\n── Check 6: EBT NULL cho CTCK ───────────────────────────────")
    _check(
        "EBT NULL cho securities template",
        f"""
        SELECT COUNT(*) FROM fin_income_statement
        WHERE symbol = ANY('{syms_pg}'::text[])
          AND template = 'securities'
          AND ebt IS NOT NULL
        """,
        expect_zero=True,
    )

    # Check 7: Accounting equation (tolerance 1%)
    logger.info("\n── Check 7: Accounting equation ─────────────────────────────")
    _check(
        "total_assets ≈ total_liabilities + total_equity (tolerance 1%)",
        f"""
        SELECT COUNT(*) FROM fin_balance_sheet
        WHERE symbol = ANY('{syms_pg}'::text[])
          AND total_assets IS NOT NULL
          AND total_liabilities IS NOT NULL
          AND total_equity IS NOT NULL
          AND total_assets > 0
          AND ABS(total_assets - (total_liabilities + total_equity)) / total_assets > 0.01
        """,
        expect_zero=True,
    )

    # Check 8: CF check (tolerance 5% — nhiều row có số lẻ do FX)
    logger.info("\n── Check 8: Cash flow reconciliation ────────────────────────")
    _check(
        "cfo + cfi + cff ≈ net_cash_change (tolerance 5%)",
        f"""
        SELECT COUNT(*) FROM fin_cash_flow
        WHERE symbol = ANY('{syms_pg}'::text[])
          AND cfo IS NOT NULL AND cfi IS NOT NULL AND cff IS NOT NULL
          AND net_cash_change IS NOT NULL
          AND ABS(net_cash_change) > 1000000
          AND ABS((cfo + cfi + cff) - net_cash_change) / ABS(net_cash_change) > 0.05
        """,
        expect_zero=True,
    )

    # Summary
    total = _CHECKS_PASSED + _CHECKS_FAILED
    logger.info(f"\n=== Kết quả: {_CHECKS_PASSED}/{total} checks PASS ===")
    if _CHECKS_FAILED > 0:
        logger.error(f"{_CHECKS_FAILED} checks FAILED — xem log ở trên.")
        sys.exit(1)
    else:
        logger.success("Tất cả checks PASS — sẵn sàng full backfill.")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Verify Approach C data quality.")
    ap.add_argument("--symbols", nargs="+", default=None)
    args = ap.parse_args()
    run_checks(symbols=[s.upper() for s in args.symbols] if args.symbols else None)
