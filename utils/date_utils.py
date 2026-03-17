"""Tiện ích xử lý chuỗi period cho pipeline."""
import re
from typing import Optional


def to_period(year: int, quarter: Optional[int] = None) -> str:
    """
    Chuyển năm/quý thành chuỗi period.
    Ví dụ: (2024, 1) → '2024Q1',  (2024, None) → '2024'
    """
    if quarter:
        return f"{year}Q{quarter}"
    return str(year)


def parse_period(period: str) -> tuple[int, Optional[int]]:
    """
    Parse chuỗi period thành (year, quarter).
    Ví dụ: '2024Q1' → (2024, 1),  '2024' → (2024, None)
    """
    match = re.fullmatch(r"(\d{4})(?:Q([1-4]))?", period.strip())
    if not match:
        raise ValueError(
            f"Định dạng period không hợp lệ: '{period}'. "
            "Mong đợi '2024' hoặc '2024Q1'."
        )
    year = int(match.group(1))
    quarter = int(match.group(2)) if match.group(2) else None
    return year, quarter


def get_period_type(period: str) -> str:
    """Trả về 'year' hoặc 'quarter' dựa trên chuỗi period."""
    _, quarter = parse_period(period)
    return "quarter" if quarter else "year"


def api_report_period_to_period(report_period: str) -> tuple[str, str]:
    """
    Chuyển đổi report_period trả về từ vnstock API sang (period, period_type).

    API trả về:
        'Q1/2024'  → ('2024Q1', 'quarter')
        'Q4/2023'  → ('2023Q4', 'quarter')
        '2024'     → ('2024',   'year')

    Trả về: (period_string, period_type)
    """
    s = str(report_period).strip()

    # Pattern: Q1/2024
    m = re.fullmatch(r"Q([1-4])/(\d{4})", s)
    if m:
        quarter, year = int(m.group(1)), int(m.group(2))
        return f"{year}Q{quarter}", "quarter"

    # Pattern: 2024 (năm)
    m = re.fullmatch(r"\d{4}", s)
    if m:
        return s, "year"

    # Fallback — giữ nguyên, đánh dấu là year
    return s, "year"
