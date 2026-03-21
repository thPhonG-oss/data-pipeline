"""Backfill job — chạy lại lịch sử cho một hoặc nhiều mã cụ thể."""
from config.constants import FINANCIAL_REPORT_TYPES
from jobs.sync_financials import run
from utils.logger import logger


def backfill(
    symbols: list[str],
    report_types: list[str] | None = None,
    max_workers: int = 3,
) -> dict:
    """
    Chạy lại toàn bộ lịch sử tài chính cho danh sách mã chỉ định.

    Dùng khi:
    - Thêm mã mới vào danh mục
    - Sửa lỗi transformer, cần re-import dữ liệu
    - Lần đầu khởi tạo

    Ví dụ:
        python -m jobs.backfill --symbols HPG FPT VCB
        python -m jobs.backfill --symbols HPG --report-types balance_sheet income_statement
    """
    logger.info(f"[backfill] Bắt đầu backfill cho: {symbols}")
    return run(symbols=symbols, report_types=report_types, max_workers=max_workers)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Backfill tài chính cho mã chứng khoán.")
    parser.add_argument(
        "--symbols", nargs="+", required=True,
        help="Danh sách mã chứng khoán, ví dụ: HPG FPT VCB",
    )
    parser.add_argument(
        "--report-types", nargs="+", default=None,
        choices=FINANCIAL_REPORT_TYPES,
        help="Loại báo cáo cần backfill. Mặc định: tất cả 4 loại.",
    )
    parser.add_argument(
        "--workers", type=int, default=3,
        help="Số luồng song song (mặc định: 3).",
    )
    args = parser.parse_args()

    result = backfill(
        symbols=[s.upper() for s in args.symbols],
        report_types=args.report_types,
        max_workers=args.workers,
    )
    logger.info(f"Kết quả: {result}")
