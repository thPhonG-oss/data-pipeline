"""
Mapping dictionary cho mẫu biểu Ngân hàng (Banking).

Áp dụng cho: ICB Level-1 = '83' (mã 8300).
Đại diện: VCB, BID, CTG, ACB, TCB, MBB, VPB, STB, HDB, SHB.

Đã xác nhận với dữ liệu thực tế VCB từ:
    Finance(symbol='VCB', period='year', source='vci').balance_sheet(lang='vi')
    Finance(symbol='VCB', period='year', source='vci').income_statement(lang='vi')
    Finance(symbol='VCB', period='year', source='vci').cash_flow(lang='vi')
"""

BALANCE_SHEET_MAP: dict[str, str] = {
    # ── Tài sản ──────────────────────────────────────────────────
    "Tiền mặt, vàng bạc, đá quý"                       : "cash_and_equivalents",
    "Tiền gửi tại Ngân hàng nhà nước Việt Nam"         : "deposits_at_state_bank",
    "Tiền gửi tại các TCTD khác và cho vay các TCTD khác": "interbank_deposits",
    "Tiền gửi tại các TCTD khác"                       : "interbank_deposits",    # fallback
    "Chứng khoán kinh doanh"                           : "trading_securities",
    "Chứng khoán đầu tư"                               : "investment_securities",
    "Cho vay khách hàng"                               : "customer_loans_gross",
    "Dự phòng rủi ro cho vay khách hàng"               : "loan_loss_reserve",      # Âm → abs()
    "Tài sản cố định"                                  : "ppe_net",
    "TỔNG TÀI SẢN"                                    : "total_assets",
    # ── Nợ phải trả ──────────────────────────────────────────────
    "Tiền gửi của khách hàng"                          : "customer_deposits",
    "Tiền gửi và vay các Tổ chức tín dụng khác"       : "interbank_borrowings",
    "Vay các tổ chức tín dụng khác"                   : "interbank_borrowings",    # fallback
    "Phát hành giấy tờ có giá"                        : "bonds_issued",
    "TỔNG NỢ PHẢI TRẢ"                               : "total_liabilities",
    # ── Vốn chủ sở hữu ───────────────────────────────────────────
    "Vốn điều lệ"                                      : "charter_capital",
    "Thặng dư vốn cổ phần"                            : "share_premium",
    "Lợi nhuận chưa phân phối"                        : "retained_earnings",
    "VỐN CHỦ SỞ HỮU"                                 : "total_equity",
    "Lợi ích của cổ đông thiểu số"                    : "minority_interest_bs",
}

INCOME_STATEMENT_MAP: dict[str, str] = {
    # ── Thu nhập lãi ─────────────────────────────────────────────
    "Thu nhập lãi và các khoản thu nhập tương tự"      : "interest_income",
    "Chi phí lãi và các chi phí tương tự"              : "interest_expense",          # Âm → abs()
    "Thu nhập lãi thuần"                               : "net_interest_income",
    # ── Thu nhập phi lãi ─────────────────────────────────────────
    "Lãi/Lỗ thuần từ hoạt động dịch vụ"               : "fee_and_commission_income",
    "Lãi/(lỗ) thuần từ hoạt động kinh doanh ngoại hối và vàng": "forex_trading_income",
    "Lãi/(lỗ) thuần từ mua bán chứng khoán kinh doanh": "trading_securities_income",
    "Lãi/(lỗ) thuần từ mua bán chứng khoán đầu tư"    : "investment_securities_income",
    "Thu nhập khác"                                    : "other_income",
    # ── Chi phí ──────────────────────────────────────────────────
    "Chi phí quản lý doanh nghiệp"                    : "operating_expenses",         # Âm → abs()
    "Trích lập dự phòng tổn thất tín dụng"             : "credit_provision_expense",   # Âm → abs()
    # ── Lợi nhuận ────────────────────────────────────────────────
    "Tổng thu nhập hoạt động"                          : "total_operating_income",
    "Lợi nhuận thuần hoạt động trước khi trích lập dự phòng tổn thất tín dụng": "pre_provision_profit",
    "Tổng lợi nhuận/lỗ trước thuế"                    : "ebt",
    "Lợi nhuận sau thuế"                               : "net_profit",
    "Cổ đông của Công ty mẹ"                          : "net_profit_parent",
    "Lợi ích của cổ đông thiểu số"                    : "minority_interest_is",
    "Lãi cơ bản trên cổ phiếu (VND)"                  : "eps_basic",
    "Lãi trên cổ phiếu pha loãng (VND)"               : "eps_diluted",
}

CASH_FLOW_MAP: dict[str, str] = {
    # ── Hoạt động kinh doanh ─────────────────────────────────────
    "Lưu chuyển tiền thuần từ các hoạt động sản xuất kinh doanh": "cfo",
    # ── Hoạt động đầu tư ─────────────────────────────────────────
    "Mua sắm TSCĐ"                                     : "capex",                      # Âm → abs()
    "Lưu chuyển tiền thuần từ hoạt động đầu tư"       : "cfi",
    # ── Hoạt động tài chính ──────────────────────────────────────
    "Cổ tức trả cho cổ đông, lợi nhuận đã chia"       : "dividends_paid",             # Âm → abs()
    # ── Tổng hợp ─────────────────────────────────────────────────
    "Lưu chuyển tiền thuần trong kỳ"                  : "net_cash_change",
    "Tiền và các khoản tương đương tiền tại thời điểm cuối kỳ": "cash_ending",
    "Tiền và các khoản tương đương tiền tài thời điểm đầu kỳ": "cash_beginning",
}
