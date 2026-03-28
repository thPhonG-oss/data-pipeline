"""
Mapping dictionary cho mẫu biểu Phi tài chính (Non-Financial).

Áp dụng cho: Tất cả công ty không thuộc ICB 8300 (Ngân hàng), 8400 (Bảo hiểm), 8500 (Chứng khoán).
Đại diện: HPG, VNM, FPT, VIC, VRE, MSN (~85% công ty niêm yết).

Tên cột lấy trực tiếp từ dữ liệu thực tế:
    - balance_sheet_year.csv   (134 cột)
    - income_statement_year.csv (44 cột)
    - cash_flow_year.csv        (81 cột)
Đã xác nhận với HPG (HoaSen, Hòa Phát — sản xuất thép).
"""

BALANCE_SHEET_MAP: dict[str, str] = {
    # ── Tài sản ngắn hạn ──────────────────────────────────────────
    "TÀI SẢN NGẮN HẠN"                     : "total_current_assets",
    "Tiền và tương đương tiền"              : "cash_and_equivalents",
    "Tiền"                                  : "cash_and_equivalents",      # Fallback nếu không có dòng tổng
    "Hàng tồn kho, ròng"                   : "inventory_net",
    "Hàng tồn kho"                          : "inventory_gross",
    "Dự phòng giảm giá hàng tồn kho"       : "inventory_allowance",
    "Phải thu khách hàng"                   : "short_term_receivables",
    "Đầu tư ngắn hạn"                      : "short_term_investments",
    # ── Tài sản dài hạn ───────────────────────────────────────────
    "TÀI SẢN DÀI HẠN"                      : "total_non_current_assets",
    "GTCL TSCĐ hữu hình"                   : "ppe_net",
    "Nguyên giá TSCĐ hữu hình"             : "ppe_gross",
    "Khấu hao lũy kế TSCĐ hữu hình"       : "accumulated_depreciation",
    "Xây dựng cơ bản đang dở dang"         : "construction_in_progress",
    "Lợi thế thương mại"                   : "goodwill",
    # ── Tổng tài sản ─────────────────────────────────────────────
    "TỔNG CỘNG TÀI SẢN"                    : "total_assets",
    # ── Nợ phải trả ──────────────────────────────────────────────
    "NỢ PHẢI TRẢ"                          : "total_liabilities",
    "Nợ ngắn hạn"                          : "total_current_liabilities",
    "Vay ngắn hạn"                         : "short_term_debt",
    "Phải trả người bán"                   : "accounts_payable",
    "Nợ dài hạn"                           : "total_long_term_liabilities",
    "Vay dài hạn"                          : "long_term_debt",
    # ── Vốn chủ sở hữu ───────────────────────────────────────────
    "Vốn chủ sở hữu"                       : "total_equity",
    "Vốn góp"                              : "charter_capital",
    "Thặng dư vốn cổ phần"                : "share_premium",
    "Lãi chưa phân phối"                   : "retained_earnings",
    "Lợi ích cổ đông không kiểm soát"     : "minority_interest_bs",
    "Tổng cộng nguồn vốn"                 : "total_liabilities_and_equity",
}

INCOME_STATEMENT_MAP: dict[str, str] = {
    # ── Doanh thu ────────────────────────────────────────────────
    "Doanh thu bán hàng và cung cấp dịch vụ" : "gross_revenue",
    "Các khoản giảm trừ doanh thu"           : "revenue_deductions",
    "Doanh thu thuần"                        : "net_revenue",
    # ── Chi phí (API trả về âm, lưu abs()) ────────────────────────
    "Giá vốn hàng bán"                       : "cost_of_goods_sold",    # Âm → abs()
    "Lợi nhuận gộp"                          : "gross_profit",
    "Doanh thu hoạt động tài chính"          : "financial_income",
    "Chi phí tài chính"                      : "financial_expenses",    # Âm → abs()
    "Chi phí lãi vay"                        : "interest_expense",      # Âm → abs()
    "Chi phí bán hàng"                       : "selling_expenses",      # Âm → abs()
    "Chi phí quản lý doanh nghiệp"           : "admin_expenses",        # Âm → abs()
    # ── Lợi nhuận ────────────────────────────────────────────────
    "Lãi/(lỗ) từ hoạt động kinh doanh"      : "operating_profit",
    "Lãi/(lỗ) trước thuế"                   : "ebt",
    "Chi phí thuế thu nhập doanh nghiệp"    : "income_tax",            # Âm → abs()
    "Lãi/(lỗ) thuần sau thuế"               : "net_profit",
    "Lợi ích của cổ đông thiểu số"          : "minority_interest_is",
    "Lợi nhuận của Cổ đông của Công ty mẹ"  : "net_profit_parent",
    "Lãi cơ bản trên cổ phiếu (VND)"        : "eps_basic",
    "Lãi trên cổ phiếu pha loãng (VND)"     : "eps_diluted",
}

CASH_FLOW_MAP: dict[str, str] = {
    # ── Điều chỉnh ───────────────────────────────────────────────
    "Lợi nhuận/(lỗ) trước thuế"                                       : "cf_ebt",
    "Khấu hao TSCĐ và BĐSĐT"                                          : "depreciation_amortization",
    "Chi phí lãi vay"                                                  : "cf_interest_expense",
    # ── Hoạt động kinh doanh ─────────────────────────────────────
    "(Tăng)/giảm các khoản phải thu"                                   : "change_in_receivables",
    "(Tăng)/giảm hàng tồn kho"                                        : "change_in_inventory",
    "Tăng/(giảm) các khoản phải trả"                                  : "change_in_payables",
    "Lưu chuyển tiền tệ ròng từ các hoạt động sản xuất kinh doanh"   : "cfo",
    # ── Hoạt động đầu tư ─────────────────────────────────────────
    "Tiền chi để mua sắm, xây dựng TSCĐ và các tài sản dài hạn khác" : "capex",   # Âm → abs()
    "Tiền thu từ thanh lý, nhượng bán TSCĐ và các tài sản dài hạn khác": "asset_disposal_proceeds",
    "Lưu chuyển tiền thuần từ hoạt động đầu tư"                      : "cfi",
    # ── Hoạt động tài chính ──────────────────────────────────────
    "Tiền thu được các khoản đi vay"                                   : "debt_proceeds",
    "Tiền trả nợ gốc vay"                                              : "debt_repayment",   # Âm → abs()
    "Cổ tức, lợi nhuận đã trả cho chủ sở hữu"                        : "dividends_paid",   # Âm → abs()
    "Lưu chuyển tiền thuần từ hoạt động tài chính"                    : "cff",
    # ── Tổng hợp ─────────────────────────────────────────────────
    "Lưu chuyển tiền thuần trong kỳ"                                   : "net_cash_change",
    "Tiền và tương đương tiền đầu kỳ"                                  : "cash_beginning",
    "Tiền và tương đương tiền cuối kỳ"                                 : "cash_ending",
}
