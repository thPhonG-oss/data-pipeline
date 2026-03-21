"""Entry point CLI cho data pipeline chứng khoán Việt Nam."""
import argparse
import sys

from utils.logger import logger


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Data Pipeline — Chứng khoán Việt Nam",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ:
  python main.py sync_listing
  python main.py sync_financials --symbol HPG VCB FPT
  python main.py sync_company --symbol HPG --workers 3
  python main.py sync_ratios
  python main.py sync_prices --symbol HPG VCB FPT
  python main.py sync_prices --full-history
  python main.py schedule
        """,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── sync_listing ──────────────────────────────────────────────────────────
    subparsers.add_parser(
        "sync_listing",
        help="Đồng bộ danh mục mã chứng khoán và phân ngành ICB",
    )

    # ── sync_financials ───────────────────────────────────────────────────────
    p_fin = subparsers.add_parser(
        "sync_financials",
        help="Đồng bộ báo cáo tài chính (balance sheet, income statement, cash flow, ratio)",
    )
    p_fin.add_argument(
        "--symbol", nargs="+", metavar="SYM",
        help="Mã cần sync (ví dụ: HPG VCB). Mặc định: tất cả mã đang niêm yết.",
    )
    p_fin.add_argument(
        "--workers", type=int, metavar="N",
        help="Số luồng song song. Mặc định: settings.max_workers.",
    )

    # ── sync_company ──────────────────────────────────────────────────────────
    p_co = subparsers.add_parser(
        "sync_company",
        help="Đồng bộ thông tin doanh nghiệp (cổ đông, lãnh đạo, công ty con, sự kiện)",
    )
    p_co.add_argument("--symbol", nargs="+", metavar="SYM")
    p_co.add_argument("--workers", type=int, metavar="N")

    # ── sync_ratios ───────────────────────────────────────────────────────────
    p_rat = subparsers.add_parser(
        "sync_ratios",
        help="Đồng bộ ratio_summary — snapshot tài chính mới nhất (chạy sau đóng cửa)",
    )
    p_rat.add_argument("--symbol", nargs="+", metavar="SYM")
    p_rat.add_argument("--workers", type=int, metavar="N")

    # ── sync_prices ───────────────────────────────────────────────────────────
    p_prices = subparsers.add_parser(
        "sync_prices",
        help="Đồng bộ giá lịch sử OHLCV (DNSE primary + VNDirect fallback)",
    )
    p_prices.add_argument(
        "--symbol", nargs="+", metavar="SYM",
        help="Mã cần sync (ví dụ: HPG VCB FPT). Mặc định: tất cả mã đang niêm yết.",
    )
    p_prices.add_argument(
        "--workers", type=int, metavar="N",
        help="Số luồng song song. Mặc định: settings.max_workers.",
    )
    p_prices.add_argument(
        "--full-history", action="store_true",
        help="Fetch lại 5 năm lịch sử (bỏ qua incremental sync).",
    )

    # ── schedule ──────────────────────────────────────────────────────────────
    subparsers.add_parser(
        "schedule",
        help="Khởi động APScheduler — chạy tất cả jobs theo lịch tự động",
    )

    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.command == "sync_listing":
        from jobs.sync_listing import run
        result = run()
        logger.info(f"Kết quả: {result}")

    elif args.command == "sync_financials":
        from jobs.sync_financials import run
        symbols = [s.upper() for s in args.symbol] if args.symbol else None
        result = run(symbols=symbols, max_workers=args.workers)
        logger.info(f"Kết quả: {result}")

    elif args.command == "sync_company":
        from jobs.sync_company import run
        symbols = [s.upper() for s in args.symbol] if args.symbol else None
        result = run(symbols=symbols, max_workers=args.workers)
        logger.info(f"Kết quả: {result}")

    elif args.command == "sync_ratios":
        from jobs.sync_ratios import run
        symbols = [s.upper() for s in args.symbol] if args.symbol else None
        result = run(symbols=symbols, max_workers=args.workers)
        logger.info(f"Kết quả: {result}")

    elif args.command == "sync_prices":
        from jobs.sync_prices import run
        symbols = [s.upper() for s in args.symbol] if args.symbol else None
        result = run(
            symbols=symbols,
            max_workers=args.workers,
            full_history=args.full_history,
        )
        logger.info(f"Kết quả: {result}")

    elif args.command == "schedule":
        from scheduler.jobs import build_scheduler
        scheduler = build_scheduler()
        logger.info("Scheduler đang chạy. Nhấn Ctrl+C để dừng.")
        logger.info("Lịch chạy:")
        for job in scheduler.get_jobs():
            next_run = getattr(job, 'next_run_time', None) or '(chưa xác định)'
            logger.info(f"  - {job.id}: {next_run}")
        try:
            scheduler.start()
        except KeyboardInterrupt:
            scheduler.shutdown()
            logger.info("Scheduler đã dừng.")
            sys.exit(0)


if __name__ == "__main__":
    main()
