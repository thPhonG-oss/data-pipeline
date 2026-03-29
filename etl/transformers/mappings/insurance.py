"""
Mapping dictionary cho mẫu biểu Bảo hiểm (Insurance).

Áp dụng cho: ICB Level-1 = '84' (mã 8400).
Đại diện: BVH, PVI, BMI, PTI, MIC, BIC.

Đã xác nhận với dữ liệu thực tế BVH từ:
    Finance(symbol='BVH', period='year', source='vci').balance_sheet(lang='vi')
    Finance(symbol='BVH', period='year', source='vci').income_statement(lang='vi')
    Finance(symbol='BVH', period='year', source='vci').cash_flow(lang='vi')
"""

BALANCE_SHEET_MAP: dict[str, str] = {
    # ── Tài sản ──────────────────────────────────────────────────
    "Tiền và các khoản tương đương tiền": "cash_and_equivalents",
    "Tiền": "cash_and_equivalents",
    "Các khoản đầu tư tài chính ngắn hạn": "financial_investments",
    "Các khoản đầu tư tài chính dài hạn": "financial_investments",  # fallback
    "Phải thu về hợp đồng bảo hiểm": "insurance_premium_receivables",
    "TÀI SẢN NGẮN HẠN": "total_current_assets",
    "TÀI SẢN DÀI HẠN": "total_non_current_assets",
    "TỔNG CỘNG TÀI SẢN": "total_assets",
    # ── Nợ phải trả ──────────────────────────────────────────────
    "Dự phòng nghiệp vụ bảo hiểm": "insurance_technical_reserves",
    "Phải trả về hợp đồng bảo hiểm": "insurance_claims_payable",
    "Vay và nợ ngắn hạn": "short_term_debt",
    "Vay và nợ dài hạn": "long_term_debt",
    "NỢ PHẢI TRẢ": "total_liabilities",
    # ── Vốn chủ sở hữu ───────────────────────────────────────────
    "Vốn đầu tư của chủ sở hữu": "charter_capital",
    "Thặng dư vốn cổ phần": "share_premium",
    "Lợi nhuận sau thuế chưa phân phối": "retained_earnings",
    "Lợi ích cổ đông thiểu số": "minority_interest_bs",
    "Vốn chủ sở hữu": "total_equity",
}

INCOME_STATEMENT_MAP: dict[str, str] = {
    # ── Doanh thu bảo hiểm ───────────────────────────────────────
    "Doanh thu phí bảo hiểm thuần": "net_insurance_premium",
    "Doanh thu thuần từ hoạt động kinh doanh bảo hiểm": "net_revenue",
    # ── Chi phí ──────────────────────────────────────────────────
    "Bồi thường thuộc trách nhiệm giữ lại": "net_insurance_claims",  # Âm → abs()
    "Chi hoa hồng bảo hiểm gốc": "insurance_acquisition_costs",  # Âm → abs()
    "Chi phí quản lý doanh nghiệp": "admin_expenses",  # Âm → abs()
    # ── Lợi nhuận ────────────────────────────────────────────────
    "Lợi nhuận thuần hoạt động kinh doanh bảo hiểm": "operating_profit",
    "Tổng lợi nhuận kế toán trước thuế": "ebt",
    "Lợi nhuận sau thuế thu nhập doanh nghiệp": "net_profit",
    "Lợi nhuận sau thuế của chủ sở hữu, tập đoàn": "net_profit_parent",
    "Lợi ích của cổ đông thiểu số": "minority_interest_is",
    "Lãi cơ bản trên cổ phiếu (VND)": "eps_basic",
    "Lãi trên cổ phiếu pha loãng (VND)": "eps_diluted",
}

CASH_FLOW_MAP: dict[str, str] = {
    "Lợi nhuận trước thuế": "cf_ebt",
    "Lưu chuyển tiền thuần từ hoạt động kinh doanh": "cfo",
    "Tiền chi mua sắm, xây dựng TSCĐ và các tài sản dài hạn khác": "capex",  # Âm → abs()
    "Lưu chuyển tiền thuần từ hoạt động đầu tư": "cfi",
    "Cổ tức, lợi nhuận đã trả cho chủ sở hữu": "dividends_paid",  # Âm → abs()
    "Lưu chuyển tiền thuần từ hoạt động tài chính": "cff",
    "Lưu chuyển tiền thuần trong kỳ": "net_cash_change",
    "Tiền và tương đương tiền đầu kỳ": "cash_beginning",
    "Tiền và tương đương cuối kỳ": "cash_ending",
}
