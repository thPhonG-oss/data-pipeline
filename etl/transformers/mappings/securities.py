"""
Mapping dictionary cho mẫu biểu Chứng khoán (Securities).

Áp dụng cho: ICB Level-1 = '85' (mã 8500).
Đại diện: SSI, VND, HCM, VCI, FTS, BSI.

Đã xác nhận với dữ liệu thực tế SSI từ:
    Finance(symbol='SSI', period='year', source='vci').balance_sheet(lang='vi')
    Finance(symbol='SSI', period='year', source='vci').income_statement(lang='vi')
    Finance(symbol='SSI', period='year', source='vci').cash_flow(lang='vi')

Ghi chú: VCI trả về tên cột viết HOA cho các dòng tổng trong KQKD và LCTT của CTCK.
"""

BALANCE_SHEET_MAP: dict[str, str] = {
    # ── Tài sản ──────────────────────────────────────────────────
    "Tiền và tương đương tiền"              : "cash_and_equivalents",
    "Tiền"                                  : "cash_and_equivalents",
    "Các tài sản tài chính ghi nhận thông qua lãi lỗ (FVTPL)": "fvtpl_assets",
    "Các khoản tài chính sẵn sàng để bán (AFS)": "available_for_sale_assets",
    "Các khoản cho vay"                    : "margin_lending",
    "TÀI SẢN NGẮN HẠN"                    : "total_current_assets",
    "GTCL TSCĐ hữu hình"                  : "ppe_net",
    "TÀI SẢN DÀI HẠN"                     : "total_non_current_assets",
    "TỔNG CỘNG TÀI SẢN"                   : "total_assets",
    # ── Nợ phải trả ──────────────────────────────────────────────
    "Phải trả hoạt động giao dịch chứng khoán": "settlement_payables",
    "Vay ngắn hạn"                         : "short_term_debt",
    "Vay dài hạn"                          : "long_term_debt",
    "NỢ PHẢI TRẢ"                          : "total_liabilities",
    # ── Vốn chủ sở hữu ───────────────────────────────────────────
    "Vốn góp của chủ sở hữu"              : "charter_capital",
    "Vốn đầu tư của chủ sở hữu"          : "charter_capital",
    "Thặng dư vốn cổ phần"                : "share_premium",
    "Lợi nhuận chưa phân phối"            : "retained_earnings",
    "Lợi ích cổ đông không kiểm soát"     : "minority_interest_bs",
    "Vốn chủ sở hữu"                      : "total_equity",
}

INCOME_STATEMENT_MAP: dict[str, str] = {
    # ── Doanh thu ────────────────────────────────────────────────
    "Doanh thu thuần về hoạt động kinh doanh"   : "net_revenue",
    "Doanh thu nghiệp vụ môi giới chứng khoán" : "brokerage_revenue",
    "Doanh thu nghiệp vụ tư vấn đầu tư chứng khoán": "advisory_revenue",
    "DOANH THU HOẠT ĐỘNG"                       : "gross_revenue",
    "CHI PHÍ HOẠT ĐỘNG"                         : "operating_expenses",              # Âm → abs()
    "KẾT QUẢ HOẠT ĐỘNG"                         : "operating_profit",
    # ── Lợi nhuận ────────────────────────────────────────────────
    "LỢI NHUẬN KẾ TOÁN SAU THUẾ"               : "net_profit",
    "Lợi nhuận sau thuế phân bổ cho chủ sở hữu": "net_profit_parent",
    "Lợi nhuận thuần phân bổ cho lợi ích của cổ đông không kiểm soát": "minority_interest_is",
    "Lãi cơ bản trên cổ phiếu (VND)"           : "eps_basic",
    "Lãi trên cổ phiếu pha loãng (VND)"        : "eps_diluted",
}

CASH_FLOW_MAP: dict[str, str] = {
    "LỢI NHUẬN TRƯỚC THUẾ"                                            : "cf_ebt",
    "Lưu chuyển thuần từ hoạt động kinh doanh"                       : "cfo",
    "Tiền chi để mua sắm, xây dựng TSCĐ, BĐSĐT và các tài sản dài hạn khác": "capex",
    "Lưu chuyển tiền thuần từ hoạt động đầu tư"                      : "cfi",
    "Cổ tức, lợi nhuận đã trả cho chủ sở hữu"                       : "dividends_paid",
    "Lưu chuyển thuần từ hoạt động tài chính"                        : "cff",
    "LƯU CHUYỂN TIỀN THUẦN TRONG KỲ"                                 : "net_cash_change",
    "TIỀN VÀ CÁC KHOẢN TƯƠNG ĐƯƠNG TIỀN ĐẦU KỲ"                    : "cash_beginning",
    "TIỀN VÀ CÁC KHOẢN TƯƠNG ĐƯƠNG TIỀN CUỐI KỲ"                   : "cash_ending",
}
