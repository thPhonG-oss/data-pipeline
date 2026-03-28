# Đặc tả kỹ thuật — Xử lý Dữ liệu Báo cáo Tài chính

**Mã tài liệu:** DS-FIN-001
**Phiên bản:** 2.0
**Trạng thái:** Bản chính thức
**Tác giả:** Nhóm Data Engineering
**Vị trí:** `/docs/financial_data_pipeline.md`
**Cập nhật:** 2026-03-28

---

## Mục lục

1. [Mục tiêu](#1-mục-tiêu)
2. [Phân tích vấn đề](#2-phân-tích-vấn-đề)
3. [Chiến lược xử lý dữ liệu & Kiến trúc](#3-chiến-lược-xử-lý-dữ-liệu--kiến-trúc)
4. [Schema cơ sở dữ liệu](#4-schema-cơ-sở-dữ-liệu)
5. [Kế hoạch triển khai](#5-kế-hoạch-triển-khai)

---

## 1. Mục tiêu

Tài liệu này đặc tả chiến lược xử lý dữ liệu end-to-end cho việc thu thập, chuẩn hóa và lưu trữ báo cáo tài chính (Bảng cân đối kế toán, Kết quả kinh doanh, Lưu chuyển tiền tệ) của tất cả công ty niêm yết trên thị trường chứng khoán Việt Nam (HOSE, HNX, UPCOM).

Mục tiêu kỹ thuật cốt lõi:

- **Chính xác:** Đảm bảo các chỉ tiêu đặc thù theo ngành được ánh xạ đúng vào trường ngữ nghĩa tương ứng, bất kể upstream API trả về cấu trúc như thế nào.
- **Bền vững:** Đảm bảo pipeline không bao giờ lỗi vì thiếu chỉ tiêu — một chỉ tiêu vắng mặt trong DataFrame được xử lý dưới dạng giá trị mặc định, không phải `KeyError`.
- **Hiệu năng truy vấn:** Hỗ trợ query screener nhanh trên các chỉ số cốt lõi mà không cần trích xuất JSONB lúc runtime.
- **Khả năng mở rộng:** Frontend có thể render toàn bộ cây chỉ tiêu cho bất kỳ công ty nào mà không cần migration schema khi upstream thêm chỉ tiêu mới.

---

## 2. Phân tích vấn đề

### 2.1 Đặc điểm dữ liệu trả về từ vnstock_data

Nguồn dữ liệu upstream (`vnstock_data`, provider VCI) trả về báo cáo tài chính qua class `Finance`:

```python
from vnstock_data import Finance

# Dữ liệu năm
fin_year    = Finance(symbol='HPG', period='year',    source='vci')
# Dữ liệu quý
fin_quarter = Finance(symbol='HPG', period='quarter', source='vci')

df_bs  = fin_year.balance_sheet(lang='vi')      # Bảng CĐKT
df_is  = fin_year.income_statement(lang='vi')   # Kết quả KD
df_cf  = fin_year.cash_flow(lang='vi')          # Lưu chuyển tiền
df_rat = fin_year.ratio(lang='vi')              # Chỉ số tài chính
```

Cấu trúc DataFrame trả về có các đặc điểm sau (đã xác nhận từ dữ liệu thực tế):

| Đặc điểm | Mô tả | Hệ quả |
|---|---|---|
| **Tên cột tiếng Việt** | Header là tên chỉ tiêu kế toán tiếng Việt đầy đủ dấu (ví dụ: `"Hàng tồn kho, ròng"`, `"Lưu chuyển tiền tệ ròng từ các hoạt động sản xuất kinh doanh"`) | Truy cập trực tiếp `df["Hàng tồn kho"]` không an toàn — tên có thể thay đổi |
| **Cột không ổn định** | Một chỉ tiêu có thể xuất hiện trong kỳ này, vắng mặt trong kỳ khác nếu giá trị bằng 0 | Phải dùng `.get()` với giá trị mặc định, không truy cập trực tiếp |
| **Cột mã thô (code columns)** | Các cột `isb25`–`isb41` (income statement), `cfb46`–`cfb221` (cash flow) là placeholder cho chỉ tiêu ngân hàng/chứng khoán — luôn bằng 0 với doanh nghiệp phi tài chính | Phải lọc bỏ trước khi upsert |
| **Giá trị âm cho chi phí** | `Giá vốn hàng bán` = `-44,165,626,148,685` (âm). Tương tự: Chi phí bán hàng, Chi phí QLDN | Phải lấy giá trị tuyệt đối khi lưu vào cột NUMERIC dương |
| **Cột `report_period`** | Nhận giá trị `"year"` hoặc `"quarter"` — dùng để phân loại kỳ báo cáo | Cần kết hợp với index để xây dựng `period` string |
| **Đơn vị tiền tệ** | VND (đồng), không chia đơn vị | Giá trị lớn (nghìn tỷ): lưu dạng `NUMERIC(20,2)` |

**Kích thước DataFrame thực tế (HPG — 10 năm dữ liệu):**

| File | Số dòng | Số cột | Ghi chú |
|---|---|---|---|
| `balance_sheet` | ~40 | 134 | Mix năm + quý |
| `income_statement` | ~40 | 44 | Gồm 17 cột `isb*` rỗng |
| `cash_flow` | ~40 | 81 | Gồm 38 cột `cfb*` rỗng |
| `ratio` | ~40 | 52 | Index: `Năm` + `Quý` |

### 2.2 Biến thể cấu trúc theo 4 mẫu biểu

Bộ Tài chính quy định 4 mẫu biểu báo cáo tài chính riêng biệt, xác định bằng **mã ICB Level-1** của doanh nghiệp:

| Mẫu biểu | ICB Level-1 | Công ty đại diện | Đặc điểm |
|---|---|---|---|
| **Phi tài chính** | Tất cả trừ 8300, 8400, 8500 | HPG, VNM, FPT, VIC | Có Hàng tồn kho, Giá vốn, Lợi nhuận gộp. Cấu trúc chi phí vận hành tiêu chuẩn |
| **Ngân hàng** | `8300` | VCB, BID, CTG, TCB | Không có HTK/GVHB. Có Cho vay KH, Thu nhập lãi thuần, Chi phí dự phòng, CAR |
| **Chứng khoán** | `8500` | SSI, VND, HCM | Có tài sản FVTPL, Dư nợ margin, Doanh thu tự doanh. Không có GVHB |
| **Bảo hiểm** | `8400` | BVH, PVI, BMI | Có Dự phòng nghiệp vụ, Phí bảo hiểm thuần, Bồi thường |

### 2.3 Tác động lên từng loại báo cáo

**Bảng cân đối kế toán:**

| Chỉ tiêu | Phi tài chính | Ngân hàng | Chứng khoán | Bảo hiểm |
|---|---|---|---|---|
| `Hàng tồn kho, ròng` | ✅ Có | ❌ N/A | ❌ N/A | ❌ N/A |
| `GTCL TSCĐ hữu hình` | ✅ Có | ⚠️ Nhỏ | ⚠️ Nhỏ | ⚠️ Nhỏ |
| `Cho vay khách hàng` | ❌ N/A | ✅ Có | ❌ N/A | ❌ N/A |
| `Tài sản FVTPL` | ❌ N/A | ❌ N/A | ✅ Có | ❌ N/A |
| `Dự phòng nghiệp vụ BH` | ❌ N/A | ❌ N/A | ❌ N/A | ✅ Có |

**Kết quả kinh doanh:**

| Chỉ tiêu | Phi tài chính | Ngân hàng | Chứng khoán | Bảo hiểm |
|---|---|---|---|---|
| `Giá vốn hàng bán` | ✅ Âm | ❌ N/A | ❌ N/A | ❌ N/A |
| `Lợi nhuận gộp` | ✅ Có | ❌ N/A | ❌ N/A | ❌ N/A |
| `Thu nhập lãi thuần` | ❌ N/A | ✅ Có | ❌ N/A | ❌ N/A |
| `Phí bảo hiểm thuần` | ❌ N/A | ❌ N/A | ❌ N/A | ✅ Có |

> **Quy tắc NULL vs. Zero:** `NULL` = chỉ tiêu **không áp dụng** cho mẫu biểu này (ngân hàng không có HTK). `0` = chỉ tiêu **có áp dụng** nhưng không được báo cáo kỳ này (có thể vì giá trị bằng 0). Hai trường hợp này có ngữ nghĩa hoàn toàn khác nhau và phải được phân biệt nghiêm ngặt.

---

## 3. Chiến lược xử lý dữ liệu & Kiến trúc

### 3.1 Tổng quan luồng xử lý

```
Finance(symbol, period, source='vci')
      |
      v
  [Extractor] — extract(symbol, report_type)
      |          trả về DataFrame thô (tên cột tiếng Việt, giá trị âm cho chi phí)
      v
  icb_code lookup từ bảng companies
      |
      v
FinanceParserFactory.get_parser(icb_code, report_type)
      |
      +-- NonFinancialParser    (ICB không phải 8300/8400/8500)
      +-- BankingParser         (ICB 8300)
      +-- SecuritiesParser      (ICB 8500)
      +-- InsuranceParser       (ICB 8400)
              |
              v
        _apply_mapping(row, mapping_dict, null_fields)
        |   → Tra cứu tên cột tiếng Việt
        |   → .get() mặc định = 0 nếu cột vắng mặt
        |   → abs() cho chi phí (GVHB, chi phí bán hàng...)
        |   → None cho chỉ tiêu không áp dụng (null_fields)
              |
              v
        _build_raw_details(row)
        |   → Serialize toàn bộ row (kể cả isb*/cfb*)
        |   → NaN/Inf → None
              |
              v
        PostgresLoader.load(payload, "financial_reports",
                            conflict_columns=["symbol","period","period_type","statement_type"])
        |   → raw_details: UPSERT bằng || (merge, không ghi đè)
              v
        PostgreSQL — bảng financial_reports
```

### 3.2 Factory Pattern — Định tuyến Parser

```python
# etl/transformers/finance_factory.py

from etl.transformers.finance_parsers import (
    NonFinancialParser, BankingParser,
    SecuritiesParser, InsuranceParser,
)

_ICB_LEVEL1_TO_PARSER = {
    "8300": BankingParser,
    "8400": InsuranceParser,
    "8500": SecuritiesParser,
}

_DEFAULT_PARSER = NonFinancialParser


class FinanceParserFactory:
    """
    Xác định parser phù hợp cho doanh nghiệp dựa trên mã ICB Level-1.

    Tất cả mã ICB không được ánh xạ rõ ràng → NonFinancialParser
    (chiếm ~85% doanh nghiệp niêm yết).
    """

    @staticmethod
    def get_parser(icb_code: str | None, statement_type: str):
        """
        Tham số:
            icb_code:       Mã ICB của công ty (2–8 ký tự, bất kỳ level nào).
                            None nếu chưa resolve → fallback NonFinancial.
            statement_type: "balance_sheet" | "income_statement" | "cash_flow"

        Trả về:
            Instance parser tương ứng, đã bind statement_type.
        """
        level1 = (icb_code or "")[:2]
        parser_class = _ICB_LEVEL1_TO_PARSER.get(level1, _DEFAULT_PARSER)
        return parser_class(statement_type=statement_type)
```

**Lý do chọn fallback NonFinancial:** Doanh nghiệp mới niêm yết chưa có `icb_code` resolved sẽ được xử lý bằng parser phi tài chính — an toàn hơn là raise exception làm dừng pipeline.

### 3.3 Mapping Dictionary — Ánh xạ tên cột

Mỗi parser định nghĩa một **mapping dictionary cho từng loại báo cáo**. Mapping dịch tên cột tiếng Việt (từ API) sang tên trường canonical snake_case trong schema DB.

Mapping là nguồn sự thật duy nhất cho ngữ nghĩa trường. Khi API đổi tên chỉ tiêu, chỉ cần cập nhật mapping — không sửa parser logic.

#### 3.3.1 Mapping Phi tài chính (HPG, VNM, FPT...)

```python
# etl/transformers/mappings/non_financial.py
# Tên cột lấy trực tiếp từ dữ liệu thực tế (balance_sheet_year.csv, income_statement_year.csv, cash_flow_year.csv)

BALANCE_SHEET_MAP: dict[str, str] = {
    # ── Tài sản ngắn hạn ─────────────────────────────────────────
    "TÀI SẢN NGẮN HẠN"                     : "total_current_assets",
    "Tiền và tương đương tiền"              : "cash_and_equivalents",
    "Tiền"                                  : "cash",
    "Các khoản tương đương tiền"            : "cash_equivalents",
    "Hàng tồn kho, ròng"                   : "inventory_net",      # Sau dự phòng
    "Hàng tồn kho"                          : "inventory_gross",    # Trước dự phòng
    "Dự phòng giảm giá hàng tồn kho"       : "inventory_allowance",
    "Phải thu khách hàng"                   : "short_term_receivables",
    "Trả trước người bán"                   : "prepaid_to_suppliers",
    "Đầu tư ngắn hạn"                      : "short_term_investments",
    # ── Tài sản dài hạn ─────────────────────────────────────────
    "TÀI SẢN DÀI HẠN"                      : "total_non_current_assets",
    "GTCL TSCĐ hữu hình"                   : "ppe_net",
    "Nguyên giá TSCĐ hữu hình"             : "ppe_gross",
    "Khấu hao lũy kế TSCĐ hữu hình"       : "accumulated_depreciation",
    "Xây dựng cơ bản đang dở dang"         : "construction_in_progress",
    "Lợi thế thương mại"                   : "goodwill",
    "Tài sản dở dang dài hạn"             : "long_term_wip",
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
    "Các khoản giảm trừ doanh thu"           : "revenue_deductions",   # Giá trị âm
    "Doanh thu thuần"                        : "net_revenue",
    # ── Chi phí (trả về âm từ API, lưu abs()) ────────────────────
    "Giá vốn hàng bán"                      : "cost_of_goods_sold",    # Âm → abs()
    "Lợi nhuận gộp"                         : "gross_profit",
    "Doanh thu hoạt động tài chính"         : "financial_income",
    "Chi phí tài chính"                     : "financial_expenses",    # Âm → abs()
    "Chi phí lãi vay"                       : "interest_expense",      # Âm → abs()
    "Chi phí bán hàng"                      : "selling_expenses",      # Âm → abs()
    "Chi phí quản lý doanh nghiệp"         : "admin_expenses",        # Âm → abs()
    # ── Lợi nhuận ────────────────────────────────────────────────
    "Lãi/(lỗ) từ hoạt động kinh doanh"     : "operating_profit",
    "Lãi/(lỗ) trước thuế"                  : "ebt",
    "Chi phí thuế thu nhập doanh nghiệp"   : "income_tax",            # Âm → abs()
    "Lãi/(lỗ) thuần sau thuế"              : "net_profit",
    "Lợi ích của cổ đông thiểu số"        : "minority_interest_is",
    "Lợi nhuận của Cổ đông của Công ty mẹ": "net_profit_parent",
    "Lãi cơ bản trên cổ phiếu (VND)"      : "eps_basic",
    "Lãi trên cổ phiếu pha loãng (VND)"   : "eps_diluted",
}

CASH_FLOW_MAP: dict[str, str] = {
    # ── Điều chỉnh ───────────────────────────────────────────────
    "Lợi nhuận/(lỗ) trước thuế"                                       : "cf_ebt",
    "Khấu hao TSCĐ và BĐSĐT"                                         : "depreciation_amortization",
    "Chi phí lãi vay"                                                  : "cf_interest_expense",
    # ── Hoạt động kinh doanh ─────────────────────────────────────
    "(Tăng)/giảm các khoản phải thu"                                  : "change_in_receivables",
    "(Tăng)/giảm hàng tồn kho"                                       : "change_in_inventory",
    "Tăng/(giảm) các khoản phải trả"                                  : "change_in_payables",
    "Lưu chuyển tiền tệ ròng từ các hoạt động sản xuất kinh doanh"  : "cfo",
    # ── Hoạt động đầu tư ─────────────────────────────────────────
    "Tiền chi để mua sắm, xây dựng TSCĐ và các tài sản dài hạn khác": "capex",   # Âm
    "Tiền thu từ thanh lý, nhượng bán TSCĐ và các tài sản dài hạn khác": "asset_disposal_proceeds",
    "Lưu chuyển tiền thuần từ hoạt động đầu tư"                      : "cfi",
    # ── Hoạt động tài chính ──────────────────────────────────────
    "Tiền thu được các khoản đi vay"                                  : "debt_proceeds",
    "Tiền trả nợ gốc vay"                                             : "debt_repayment",  # Âm
    "Cổ tức, lợi nhuận đã trả cho chủ sở hữu"                       : "dividends_paid",  # Âm
    "Lưu chuyển tiền thuần từ hoạt động tài chính"                   : "cff",
    # ── Tổng hợp ─────────────────────────────────────────────────
    "Lưu chuyển tiền thuần trong kỳ"                                  : "net_cash_change",
    "Tiền và tương đương tiền đầu kỳ"                                 : "cash_beginning",
    "Tiền và tương đương tiền cuối kỳ"                                : "cash_ending",
}
```

#### 3.3.2 Mapping Ngân hàng (VCB, BID, CTG...)

```python
# etl/transformers/mappings/banking.py
# Không có HTK, GVHB, Lợi nhuận gộp
# Tên cột banking cần xác nhận bằng dữ liệu thực tế từ VCB/BID

BALANCE_SHEET_MAP: dict[str, str] = {
    "Tiền mặt, vàng bạc, đá quý"                       : "cash_and_equivalents",
    "Tiền gửi tại NHNN"                                 : "deposits_at_state_bank",
    "Tiền gửi tại và cho vay các TCTD khác"            : "interbank_deposits",
    "Chứng khoán kinh doanh"                           : "trading_securities",
    "Cho vay khách hàng"                               : "customer_loans_gross",
    "Dự phòng rủi ro cho vay khách hàng"               : "loan_loss_reserve",       # Âm
    "Tổng tài sản"                                     : "total_assets",
    "Tiền gửi của khách hàng"                          : "customer_deposits",
    "Tiền gửi của các TCTD khác"                       : "interbank_borrowings",
    "Vốn điều lệ"                                      : "charter_capital",
    "Vốn chủ sở hữu"                                   : "total_equity",
    # HTK, TSCĐ hữu hình lớn: không có → sẽ được force NULL
}

INCOME_STATEMENT_MAP: dict[str, str] = {
    "Thu nhập lãi và các khoản tương đương"            : "interest_income",
    "Chi phí lãi và các khoản tương đương"             : "interest_expense",        # Âm
    "Thu nhập lãi thuần"                               : "net_interest_income",
    "Lãi/lỗ thuần từ hoạt động dịch vụ"               : "fee_and_commission_income",
    "Lãi/lỗ thuần từ kinh doanh ngoại hối"            : "forex_trading_income",
    "Lãi/lỗ thuần từ mua bán chứng khoán kinh doanh"  : "trading_securities_income",
    "Chi phí dự phòng rủi ro tín dụng"                : "credit_provision_expense", # Âm
    "Tổng thu nhập hoạt động"                         : "total_operating_income",
    "Chi phí hoạt động"                               : "operating_expenses",       # Âm
    "Lợi nhuận thuần từ HĐKD trước dự phòng"         : "pre_provision_profit",
    "Lợi nhuận trước thuế"                            : "ebt",
    "Lợi nhuận sau thuế"                              : "net_profit",
    # Giá vốn, Lợi nhuận gộp, Chi phí bán hàng: không có → force NULL
}

CASH_FLOW_MAP: dict[str, str] = {
    "Lợi nhuận trước thuế"                                            : "cf_ebt",
    "Lưu chuyển tiền tệ ròng từ hoạt động kinh doanh"               : "cfo",
    "Lưu chuyển tiền thuần từ hoạt động đầu tư"                     : "cfi",
    "Lưu chuyển tiền thuần từ hoạt động tài chính"                  : "cff",
    "Lưu chuyển tiền thuần trong kỳ"                                 : "net_cash_change",
    "Tiền và tương đương tiền đầu kỳ"                                : "cash_beginning",
    "Tiền và tương đương tiền cuối kỳ"                               : "cash_ending",
}
```

> **Lưu ý quan trọng:** Mapping ngân hàng, chứng khoán, bảo hiểm cần được xác nhận bằng dữ liệu thực tế từ `Finance(symbol='VCB')`, `Finance(symbol='SSI')`, `Finance(symbol='BVH')` trong bước Phase 2 của kế hoạch triển khai.

### 3.4 Quy tắc xử lý trường thiếu — Missing Field Policy

**Quy tắc cứng:**

| Trường hợp | Giá trị lưu | Lý do |
|---|---|---|
| Cột có trong mapping, **có** trong DataFrame | Giá trị thực (đã abs() nếu cần) | Dữ liệu hợp lệ |
| Cột có trong mapping, **không có** trong DataFrame | `0` | Áp dụng nhưng không được báo cáo kỳ này |
| Cột trong `null_fields` (không áp dụng cho template) | `None` | Ngữ nghĩa khác biệt với 0 |
| Cột `isb*` / `cfb*` (mã thô rỗng) | Bỏ qua trong typed columns; lưu trong `raw_details` | Placeholder, không có ngữ nghĩa |

```python
# etl/transformers/finance_parsers.py

from abc import ABC, abstractmethod
import pandas as pd

# Tập các cột mã thô cần loại bỏ khỏi typed columns
_RAW_CODE_PREFIXES = ("isb", "cfb", "bsa", "bsb", "bss", "noc")


class BaseFinancialParser(ABC):
    """
    Lớp cơ sở cho tất cả parser báo cáo tài chính.

    Subclass định nghĩa FIELD_MAPS và NULL_FIELDS.
    """

    FIELD_MAPS: dict[str, dict[str, str]] = {}
    NULL_FIELDS: dict[str, set[str]] = {}

    # Tập cột chi phí cần lấy giá trị tuyệt đối
    # (API trả về âm, DB lưu dương để dễ tính toán)
    ABS_FIELDS: set[str] = {
        "cost_of_goods_sold", "financial_expenses", "interest_expense",
        "selling_expenses", "admin_expenses", "income_tax",
        "capex", "debt_repayment", "dividends_paid",
        "credit_provision_expense", "loan_loss_reserve",
    }

    def __init__(self, statement_type: str) -> None:
        valid = {"balance_sheet", "income_statement", "cash_flow"}
        if statement_type not in valid:
            raise ValueError(f"statement_type không hợp lệ: '{statement_type}'. Chọn: {valid}")
        self.statement_type = statement_type

    def parse(self, df: pd.DataFrame, symbol: str) -> list[dict]:
        """
        Parse tất cả kỳ có trong df.

        Tham số:
            df:     DataFrame thô từ vnstock_data Finance extractor.
                    Có cột 'report_period' ('year'|'quarter') và index chứa nhãn kỳ.
            symbol: Mã cổ phiếu.

        Trả về:
            Danh sách payload dict, mỗi dict ứng với một kỳ báo cáo.
        """
        mapping     = self.FIELD_MAPS.get(self.statement_type, {})
        null_fields = self.NULL_FIELDS.get(self.statement_type, set())
        payloads    = []

        for period_label, row in df.iterrows():
            period, period_type = self._parse_period(str(period_label))
            core        = self._apply_mapping(row, mapping, null_fields)
            raw_details = self._build_raw_details(row)

            payloads.append({
                "symbol":         symbol,
                "period":         period,
                "period_type":    period_type,
                "statement_type": self.statement_type,
                "template":       self._template_name(),
                "source":         "vci",
                **core,
                "raw_details":    raw_details,
            })

        return payloads

    def _apply_mapping(
        self,
        row: pd.Series,
        mapping: dict[str, str],
        null_fields: set[str],
    ) -> dict:
        """
        Resolve từng trường canonical từ row dùng mapping dict.

        Thứ tự ưu tiên:
          1. Trong null_fields                    → None
          2. Cột nguồn có trong row               → giá trị số (abs() nếu cần)
          3. Cột nguồn không có trong row         → 0
        """
        result  = {}
        reverse = {v: k for k, v in mapping.items()}  # canonical → tên cột tiếng Việt

        for canonical in set(mapping.values()):
            if canonical in null_fields:
                result[canonical] = None
                continue

            source_col = reverse.get(canonical)
            if source_col and source_col in row.index:
                val = self._to_numeric(row[source_col])
                if val is not None and canonical in self.ABS_FIELDS:
                    val = abs(val)
                result[canonical] = val if val is not None else 0
            else:
                result[canonical] = 0

        return result

    def _build_raw_details(self, row: pd.Series) -> dict:
        """
        Serialize toàn bộ row thành dict cho raw_details JSONB.
        Loại bỏ cột mã thô (isb*, cfb*) vì không có ngữ nghĩa.
        Chuyển NaN/Inf → None.
        """
        raw = {}
        for col, val in row.items():
            col_str = str(col)
            # Loại bỏ placeholder codes nhưng vẫn lưu trong raw để audit
            if pd.isna(val):
                raw[col_str] = None
            elif isinstance(val, float) and not pd.isfinite(val):
                raw[col_str] = None
            else:
                raw[col_str] = (
                    val if isinstance(val, (int, float, str, bool, type(None)))
                    else str(val)
                )
        return raw

    @staticmethod
    def _to_numeric(val) -> float | None:
        """Chuyển về float. Trả None khi thất bại."""
        if val is None or (isinstance(val, float) and not pd.isfinite(val)):
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_period(label: str) -> tuple[str, str]:
        """
        Phân tích nhãn kỳ báo cáo.

        Ví dụ:
            "2024"    → ("2024",   "year")
            "Q1/2024" → ("2024Q1", "quarter")
            "Q4/2023" → ("2023Q4", "quarter")
        """
        label = label.strip()
        if label.startswith("Q"):
            parts   = label.split("/")
            quarter = parts[0]
            year    = parts[1] if len(parts) > 1 else "0000"
            return f"{year}{quarter}", "quarter"
        return label, "year"

    @abstractmethod
    def _template_name(self) -> str:
        """Tên template lưu trong DB."""


class NonFinancialParser(BaseFinancialParser):
    from etl.transformers.mappings.non_financial import (
        BALANCE_SHEET_MAP, INCOME_STATEMENT_MAP, CASH_FLOW_MAP,
    )
    FIELD_MAPS = {
        "balance_sheet":    BALANCE_SHEET_MAP,
        "income_statement": INCOME_STATEMENT_MAP,
        "cash_flow":        CASH_FLOW_MAP,
    }
    NULL_FIELDS = {
        # Không có chỉ tiêu nào force NULL với phi tài chính
        "balance_sheet":    set(),
        "income_statement": set(),
        "cash_flow":        set(),
    }
    def _template_name(self) -> str: return "non_financial"


class BankingParser(BaseFinancialParser):
    from etl.transformers.mappings.banking import (
        BALANCE_SHEET_MAP, INCOME_STATEMENT_MAP, CASH_FLOW_MAP,
    )
    FIELD_MAPS = {
        "balance_sheet":    BALANCE_SHEET_MAP,
        "income_statement": INCOME_STATEMENT_MAP,
        "cash_flow":        CASH_FLOW_MAP,
    }
    NULL_FIELDS = {
        # Chỉ tiêu không có ngữ nghĩa với ngân hàng → force NULL
        "balance_sheet":    {
            "inventory_net", "inventory_gross", "inventory_allowance",
            "ppe_gross", "accumulated_depreciation", "construction_in_progress",
        },
        "income_statement": {
            "cost_of_goods_sold", "gross_profit",
            "selling_expenses", "admin_expenses",
        },
        "cash_flow":        set(),
    }
    def _template_name(self) -> str: return "banking"


class SecuritiesParser(BaseFinancialParser):
    # Mapping tương tự — xem etl/transformers/mappings/securities.py
    NULL_FIELDS = {
        "balance_sheet":    {"inventory_net", "inventory_gross", "inventory_allowance"},
        "income_statement": {"cost_of_goods_sold", "gross_profit"},
        "cash_flow":        set(),
    }
    def _template_name(self) -> str: return "securities"


class InsuranceParser(BaseFinancialParser):
    # Mapping tương tự — xem etl/transformers/mappings/insurance.py
    NULL_FIELDS = {
        "balance_sheet":    {"inventory_net", "inventory_gross", "inventory_allowance"},
        "income_statement": {"cost_of_goods_sold", "gross_profit"},
        "cash_flow":        set(),
    }
    def _template_name(self) -> str: return "insurance"
```

### 3.5 Xây dựng Hybrid JSONB Payload

```
DataFrame row (134 cột BS / 44 cột IS / 81 cột CF — tên tiếng Việt)
        |
        +-- _apply_mapping() ──────► core_fields (15-25 trường NUMERIC canonical)
        |   - Tra mapping dict                      Lưu vào: cột NUMERIC trong DB
        |   - .get() mặc định = 0
        |   - abs() cho chi phí
        |   - None cho null_fields
        |
        +-- _build_raw_details() ──► raw dict (toàn bộ row, đã sanitize)
            - Giữ tất cả cột tiếng Việt               Lưu vào: raw_details JSONB
            - Giữ cả isb*/cfb* (audit trail)
            - NaN/Inf → None
```

**Quy tắc merge khi upsert:**

```sql
-- ON CONFLICT DO UPDATE — raw_details dùng || để tích lũy, không ghi đè
raw_details = financial_reports.raw_details || EXCLUDED.raw_details
```

Điều này đảm bảo: nếu một chỉ tiêu có trong sync kỳ trước nhưng vắng mặt trong sync kỳ này (vì bằng 0), dữ liệu vẫn được giữ lại trong JSONB.

---

## 4. Schema cơ sở dữ liệu

### 4.1 Lý do thiết kế một bảng thống nhất

Dùng **một bảng duy nhất** `financial_reports` cho tất cả loại báo cáo và tất cả template thay vì 12 bảng riêng (4 template × 3 loại báo cáo). Cột `statement_type` và `template` làm discriminator.

Lợi thế:
- **Screener query:** `WHERE total_assets > 1e12 AND net_profit > 0` chạy với index support trên cột NUMERIC
- **Tổng hợp chuỗi thời gian:** `AVG(net_profit)`, `SUM(cfo)` cần cột typed
- **Ổn định vận hành:** Không cần quản lý 12 bảng riêng biệt

### 4.2 Script CREATE TABLE

```sql
-- ============================================================
-- Migration 014: financial_reports
--
-- Bảng thống nhất cho BCĐKT, KQKD, LCTT
-- của tất cả 4 mẫu biểu (Phi tài chính, Ngân hàng, Chứng khoán, Bảo hiểm)
--
-- Conflict key: (symbol, period, period_type, statement_type)
-- ============================================================

CREATE TYPE IF NOT EXISTS statement_type_enum AS ENUM (
    'balance_sheet',        -- Bảng cân đối kế toán
    'income_statement',     -- Kết quả kinh doanh
    'cash_flow'             -- Lưu chuyển tiền tệ
);

CREATE TYPE IF NOT EXISTS period_type_enum AS ENUM (
    'year',     -- Năm: "2024"
    'quarter'   -- Quý: "2024Q1", "2024Q2"...
);

CREATE TYPE IF NOT EXISTS fin_template_enum AS ENUM (
    'non_financial',  -- Phi tài chính (sản xuất, bán lẻ, công nghệ...)
    'banking',        -- Ngân hàng (ICB 8300)
    'securities',     -- Chứng khoán (ICB 8500)
    'insurance'       -- Bảo hiểm (ICB 8400)
);

CREATE TABLE IF NOT EXISTS financial_reports (

    -- ── Định danh ─────────────────────────────────────────────────
    id              BIGSERIAL            PRIMARY KEY,
    symbol          VARCHAR(10)          NOT NULL REFERENCES companies(symbol),
    period          VARCHAR(10)          NOT NULL,   -- "2024" | "2024Q1"
    period_type     period_type_enum     NOT NULL,
    statement_type  statement_type_enum  NOT NULL,
    template        fin_template_enum    NOT NULL,
    source          VARCHAR(20)          NOT NULL DEFAULT 'vci',

    -- ── Tài sản — Cross-Industry Core ─────────────────────────────
    -- NULL = không áp dụng cho template này
    -- 0    = áp dụng nhưng không được báo cáo kỳ này
    cash_and_equivalents        NUMERIC(20, 2),  -- Tiền và tương đương tiền
    total_current_assets        NUMERIC(20, 2),  -- TÀI SẢN NGẮN HẠN
    total_non_current_assets    NUMERIC(20, 2),  -- TÀI SẢN DÀI HẠN
    total_assets                NUMERIC(20, 2),  -- TỔNG CỘNG TÀI SẢN
    total_liabilities           NUMERIC(20, 2),  -- NỢ PHẢI TRẢ
    total_equity                NUMERIC(20, 2),  -- Vốn chủ sở hữu
    charter_capital             NUMERIC(20, 2),  -- Vốn góp / Vốn điều lệ
    short_term_debt             NUMERIC(20, 2),  -- Vay ngắn hạn
    long_term_debt              NUMERIC(20, 2),  -- Vay dài hạn
    retained_earnings           NUMERIC(20, 2),  -- Lãi chưa phân phối

    -- ── Tài sản — Phi tài chính (NULL với Banking/Insurance) ──────
    inventory_net               NUMERIC(20, 2),  -- Hàng tồn kho, ròng (sau dự phòng)
    inventory_gross             NUMERIC(20, 2),  -- Hàng tồn kho (trước dự phòng)
    short_term_receivables      NUMERIC(20, 2),  -- Phải thu khách hàng
    ppe_net                     NUMERIC(20, 2),  -- GTCL TSCĐ hữu hình
    ppe_gross                   NUMERIC(20, 2),  -- Nguyên giá TSCĐ hữu hình
    accumulated_depreciation    NUMERIC(20, 2),  -- Khấu hao lũy kế TSCĐ hữu hình
    construction_in_progress    NUMERIC(20, 2),  -- Xây dựng cơ bản đang dở dang

    -- ── Tài sản — Ngân hàng (NULL với Non-Financial) ──────────────
    customer_loans_gross        NUMERIC(20, 2),  -- Cho vay khách hàng (trước dự phòng)
    loan_loss_reserve           NUMERIC(20, 2),  -- Dự phòng rủi ro cho vay KH
    customer_deposits           NUMERIC(20, 2),  -- Tiền gửi của khách hàng

    -- ── KQKD — Cross-Industry Core ────────────────────────────────
    net_revenue                 NUMERIC(20, 2),  -- Doanh thu thuần
    operating_profit            NUMERIC(20, 2),  -- Lãi/(lỗ) từ hoạt động kinh doanh
    ebt                         NUMERIC(20, 2),  -- Lãi/(lỗ) trước thuế
    net_profit                  NUMERIC(20, 2),  -- Lãi/(lỗ) thuần sau thuế
    net_profit_parent           NUMERIC(20, 2),  -- Lợi nhuận của Cổ đông Công ty mẹ
    eps_basic                   NUMERIC(15, 2),  -- Lãi cơ bản trên cổ phiếu (VND)

    -- ── KQKD — Phi tài chính (NULL với Banking/Insurance) ─────────
    gross_revenue               NUMERIC(20, 2),  -- Doanh thu bán hàng và CCDV
    cost_of_goods_sold          NUMERIC(20, 2),  -- Giá vốn hàng bán (đã abs())
    gross_profit                NUMERIC(20, 2),  -- Lợi nhuận gộp
    selling_expenses            NUMERIC(20, 2),  -- Chi phí bán hàng (đã abs())
    admin_expenses              NUMERIC(20, 2),  -- Chi phí quản lý doanh nghiệp (đã abs())
    interest_expense            NUMERIC(20, 2),  -- Chi phí lãi vay (đã abs())

    -- ── KQKD — Ngân hàng (NULL với Non-Financial) ─────────────────
    net_interest_income         NUMERIC(20, 2),  -- Thu nhập lãi thuần
    credit_provision_expense    NUMERIC(20, 2),  -- Chi phí dự phòng rủi ro tín dụng (đã abs())

    -- ── LCTT — Core (tất cả template) ─────────────────────────────
    cfo                         NUMERIC(20, 2),  -- Lưu chuyển tiền từ HĐKD (có thể âm)
    cfi                         NUMERIC(20, 2),  -- Lưu chuyển tiền từ HĐ đầu tư
    cff                         NUMERIC(20, 2),  -- Lưu chuyển tiền từ HĐ tài chính
    capex                       NUMERIC(20, 2),  -- Chi TSCĐ (đã abs())
    net_cash_change             NUMERIC(20, 2),  -- Lưu chuyển tiền thuần trong kỳ
    cash_beginning              NUMERIC(20, 2),  -- Tiền đầu kỳ
    cash_ending                 NUMERIC(20, 2),  -- Tiền cuối kỳ

    -- ── Lưu trữ thô ───────────────────────────────────────────────
    -- Toàn bộ row từ API (tên cột tiếng Việt đầy đủ dấu, kể cả isb*/cfb*)
    -- Merge strategy khi upsert: raw_details || EXCLUDED.raw_details
    raw_details                 JSONB        NOT NULL DEFAULT '{}',

    -- ── Audit ─────────────────────────────────────────────────────
    fetched_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    -- ── Ràng buộc ─────────────────────────────────────────────────
    CONSTRAINT uq_financial_reports
        UNIQUE (symbol, period, period_type, statement_type)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_fr_symbol_period
    ON financial_reports (symbol, period_type, period DESC);

CREATE INDEX IF NOT EXISTS idx_fr_period_template
    ON financial_reports (period, period_type, template);

CREATE INDEX IF NOT EXISTS idx_fr_symbol_stmt
    ON financial_reports (symbol, statement_type);

CREATE INDEX IF NOT EXISTS idx_fr_raw_details_gin
    ON financial_reports USING GIN (raw_details);

-- Partial index cho báo cáo năm (truy vấn phổ biến nhất)
CREATE INDEX IF NOT EXISTS idx_fr_annual
    ON financial_reports (symbol, period DESC)
    WHERE period_type = 'year';
```

### 4.3 Ràng buộc ngữ nghĩa NULL

```sql
-- Ngân hàng phải có NULL cho inventory (không phải 0)
-- Ngăn ngân hàng xuất hiện trong screener hàng tồn kho
ALTER TABLE financial_reports
    ADD CONSTRAINT chk_banking_null_inventory
    CHECK (NOT (template = 'banking' AND inventory_net IS NOT NULL));

-- Ngân hàng phải có NULL cho cost_of_goods_sold
ALTER TABLE financial_reports
    ADD CONSTRAINT chk_banking_null_cogs
    CHECK (NOT (template = 'banking' AND cost_of_goods_sold IS NOT NULL));

-- Phi tài chính phải có NULL cho customer_loans_gross
ALTER TABLE financial_reports
    ADD CONSTRAINT chk_nonfinancial_null_loans
    CHECK (NOT (template = 'non_financial' AND customer_loans_gross IS NOT NULL));

-- Phi tài chính phải có NULL cho net_interest_income
ALTER TABLE financial_reports
    ADD CONSTRAINT chk_nonfinancial_null_nii
    CHECK (NOT (template = 'non_financial' AND net_interest_income IS NOT NULL));
```

> **Lưu ý triển khai:** Thêm constraint dưới dạng `NOT VALID` khi migration ban đầu. Chạy `VALIDATE CONSTRAINT` sau khi kiểm tra 100% dữ liệu production để tránh lock bảng.

### 4.4 Ví dụ Query thực tế

```sql
-- Screener: Doanh nghiệp phi tài chính có lãi, FCF dương, năm 2024
SELECT
    fr_is.symbol,
    fr_is.net_revenue,
    fr_is.gross_profit,
    fr_is.net_profit,
    fr_cf.cfo,
    fr_cf.capex,
    (fr_cf.cfo - fr_cf.capex) AS free_cash_flow
FROM financial_reports fr_is
JOIN financial_reports fr_cf
    ON fr_is.symbol = fr_cf.symbol
    AND fr_is.period = fr_cf.period
    AND fr_cf.statement_type = 'cash_flow'
WHERE fr_is.statement_type = 'income_statement'
  AND fr_is.period_type    = 'year'
  AND fr_is.period         = '2024'
  AND fr_is.template       = 'non_financial'
  AND fr_is.net_profit     > 0
  AND fr_cf.cfo            > fr_cf.capex
ORDER BY free_cash_flow DESC;

-- Screener ngân hàng: NIM cao, nợ xấu thấp (dùng raw_details)
SELECT
    symbol, period,
    net_interest_income,
    total_assets,
    customer_loans_gross,
    (net_interest_income::float / NULLIF(total_assets, 0)) AS nim_proxy
FROM financial_reports
WHERE statement_type = 'income_statement'
  AND period_type   = 'year'
  AND period        = '2024'
  AND template      = 'banking'
  AND net_interest_income > 1e12
ORDER BY nim_proxy DESC;

-- Lấy toàn bộ cây chỉ tiêu cho Frontend render (tiếng Việt)
SELECT raw_details
FROM financial_reports
WHERE symbol         = 'HPG'
  AND statement_type = 'balance_sheet'
  AND period_type    = 'year'
ORDER BY period DESC
LIMIT 5;

-- Kiểm tra chỉ tiêu cụ thể qua JSONB
SELECT symbol, period,
       raw_details->>'Hàng tồn kho, ròng' AS inventory_raw
FROM financial_reports
WHERE template       = 'non_financial'
  AND statement_type = 'balance_sheet'
  AND period         = '2024'
  AND raw_details ? 'Hàng tồn kho, ròng';
```

---

## 5. Kế hoạch triển khai

### 5.1 Work Breakdown Structure (WBS)

Triển khai chia làm 4 phase tuần tự. Có thể song song hóa trong mỗi phase như ghi chú bên dưới.

---

#### Phase 1 — Schema & Migration (Tuần 1)

**Phụ trách:** Data Engineer A
**Kết quả:** `db/migrations/014_financial_reports.sql` đã chạy trên staging.

| Task | Mô tả |
|---|---|
| 1.1 | Viết script CREATE TABLE theo §4.2. Đặc biệt chú ý kiểu NUMERIC(20,2) cho tất cả giá trị tiền tệ VND |
| 1.2 | Định nghĩa 3 ENUM types (statement_type, period_type, fin_template) |
| 1.3 | Tạo 5 indexes + 4 CHECK constraints theo §4.3 (thêm dạng NOT VALID trước) |
| 1.4 | Chạy migration trên local và staging. Xác nhận qua `\d financial_reports` |
| 1.5 | Cập nhật `config/constants.py`: thêm `CONFLICT_KEYS["financial_reports"]` = `["symbol", "period", "period_type", "statement_type"]` |
| 1.6 | Cập nhật `PostgresLoader`: upsert `raw_details` dùng `||` (JSONB merge), không ghi đè |

**Tiêu chí nghiệm thu:**
`SELECT * FROM financial_reports LIMIT 0` trả về đúng danh sách cột. Migration idempotent (chạy 2 lần không lỗi). CHECK constraints active.

---

#### Phase 2 — Mapping Dictionary (Tuần 1–2, song song với Phase 1)

**Phụ trách:** Data Engineer B
**Kết quả:** `etl/transformers/mappings/` — 4 module, mỗi module có 3 mapping dict.

| Task | Mô tả |
|---|---|
| 2.1 | Export dữ liệu thực tế cho 4 mẫu biểu bằng Jupyter notebook trong `jupyter_test/finance/`: HPG (phi tài chính — đã có), VCB (ngân hàng), SSI (chứng khoán), BVH (bảo hiểm) |
| 2.2 | Liệt kê đầy đủ tên cột tiếng Việt xuất hiện trong mỗi tổ hợp (template × loại báo cáo) qua ít nhất 8 kỳ báo cáo |
| 2.3 | Xác nhận các cột chi phí trả về âm (GVHB, chi phí bán hàng...) và bổ sung vào `ABS_FIELDS` |
| 2.4 | Viết 4 module mapping: `non_financial.py`, `banking.py`, `securities.py`, `insurance.py` |
| 2.5 | Peer-review mapping với chuẩn mực VAS. Ghi chú các chỉ tiêu mơ hồ hoặc xuất hiện nhiều lần |
| 2.6 | Xác định `NULL_FIELDS` cho từng template × loại báo cáo |

**Tiêu chí nghiệm thu:**
Với 10 công ty mẫu (2–3 mỗi template), `_apply_mapping()` không phát sinh `KeyError`. Các trường `total_assets`, `total_equity`, `net_profit` có giá trị khác 0 với tất cả công ty có dữ liệu.

---

#### Phase 3 — Parser & Factory (Tuần 2)

**Phụ trách:** DE-A + DE-B
**Kết quả:** `etl/transformers/finance_factory.py`, `etl/transformers/finance_parsers.py`.

| Task | Mô tả | Phụ trách |
|---|---|---|
| 3.1 | Implement `BaseFinancialParser`: `parse()`, `_apply_mapping()`, `_build_raw_details()`, `_to_numeric()`, `_parse_period()` | DE-A |
| 3.2 | Implement 4 subclass: `NonFinancialParser`, `BankingParser`, `SecuritiesParser`, `InsuranceParser` | DE-B |
| 3.3 | Implement `FinanceParserFactory.get_parser()` | DE-A |
| 3.4 | Viết unit test `tests/test_finance_parsers.py`: mock DataFrame cho từng template, assert giá trị core, assert null_fields → None, assert cột thiếu → 0 (không KeyError), assert chi phí đã abs(). Mục tiêu: ≥ 90% branch coverage | DE-A + DE-B |
| 3.5 | Integration test với dữ liệu thực: HPG, VCB, SSI, BVH. Load vào staging DB. Verify row count và sanity (không có total_assets = 0) | DE-B |

**Tiêu chí nghiệm thu:**
Tất cả unit test pass. Integration test: 0 failed rows với 4 công ty × 3 loại báo cáo × 8 kỳ.

---

#### Phase 4 — Tích hợp Job & Backend API (Tuần 3)

**Phụ trách:** Backend Dev A + Backend Dev B (song song với DE validation)

| Task | Mô tả | Phụ trách |
|---|---|---|
| 4.1 | Refactor `jobs/sync_financials.py`: gọi `FinanceParserFactory.get_parser(icb_code, statement_type)` per symbol. Resolve `icb_code` từ bảng `companies` trước khi dispatch | DE-A |
| 4.2 | Cập nhật `PostgresLoader` cho `financial_reports`: conflict key 4 cột; `raw_details` merge dùng `||` | DE-A |
| 4.3 | Implement endpoint `GET /api/v1/financials/{symbol}`: nhận `statement_type`, `period_type`, `from_period`, `to_period`. Trả về typed columns + `raw_details` | BE-A |
| 4.4 | Implement endpoint `GET /api/v1/screener/financials`: filter trên typed NUMERIC columns (không dùng JSONB extraction trong WHERE). Mục tiêu < 200ms cho toàn bộ ~1,550 mã | BE-B |
| 4.5 | Implement endpoint `GET /api/v1/financials/{symbol}/raw`: trả về `raw_details` JSONB để Frontend render cây chỉ tiêu tiếng Việt đầy đủ | BE-B |
| 4.6 | Load production toàn bộ ~1,550 mã. Monitor `pipeline_logs`. Mục tiêu failure rate < 1% | DE-B |

**Tiêu chí nghiệm thu:**
- `sync_financials` full run: failure rate < 1%
- Screener endpoint < 200ms (xác nhận qua `EXPLAIN ANALYZE`, index-only scan)
- `raw_details` endpoint trả đúng tên cột tiếng Việt cho VCB (ngân hàng) và HPG (phi tài chính) — không bị lẫn dữ liệu giữa các template
- Không có `NULL` trong `total_assets` hoặc `net_profit` với công ty có dữ liệu (NULL = lỗi mapping, không phải giá trị báo cáo)

### 5.2 Sơ đồ phụ thuộc

```
Phase 1 (Schema & Migration)
        |
        +-----------> Phase 2 (Mapping Dictionaries) ----> Phase 3 (Parser & Factory)
        |                                                           |
        +-----------------------------------------------------------+
                                                                    |
                                                                    v
                                                        Phase 4 (Job Integration & API)
```

### 5.3 Bảng rủi ro

| Rủi ro | Khả năng | Mức độ | Biện pháp xử lý |
|---|---|---|---|
| API vnstock đổi tên cột tiếng Việt không báo trước | Cao | Trung bình | Mapping miss → giá trị `0` (không crash pipeline). Monitor `total_assets = 0` trong `pipeline_logs`; alert nếu > 5% rows trong một kỳ |
| `icb_code` chưa được resolve cho công ty mới niêm yết | Trung bình | Thấp | Factory fallback NonFinancialParser. Đảm bảo `sync_listing` + `sync_company` chạy trước `sync_financials` trong scheduler |
| Cột `isb*`/`cfb*` chiếm dung lượng `raw_details` không cần thiết | Thấp | Thấp | Theo dõi `pg_column_size(raw_details)` hàng tháng. Cân nhắc lọc bỏ các cột code = 0 trong `_build_raw_details()` nếu trung bình > 20KB/row |
| CHECK constraint từ chối dữ liệu hợp lệ do phân loại template sai | Thấp | Cao | Thêm constraint dạng `NOT VALID`. Chạy `VALIDATE CONSTRAINT` sau khi kiểm tra 100% production. Kiểm tra chéo danh sách ngân hàng: VCB, BID, CTG, ACB, TCB, MBB, VPB, STB, HDB, SHB |
| Giá trị âm của chi phí không được abs() dẫn đến kết quả screener sai | Trung bình | Cao | Unit test bắt buộc assert abs(): `assert parser.parse(df)[0]["cost_of_goods_sold"] > 0` với input âm |

### 5.4 Cấu trúc file sau khi hoàn thành

```
etl/
  transformers/
    finance_factory.py              ← FinanceParserFactory
    finance_parsers.py              ← BaseFinancialParser + 4 subclass
    mappings/
      __init__.py
      non_financial.py              ← BS/IS/CF mapping (xác nhận từ HPG thực tế)
      banking.py                    ← BS/IS/CF mapping (xác nhận từ VCB thực tế)
      securities.py                 ← BS/IS/CF mapping (xác nhận từ SSI thực tế)
      insurance.py                  ← BS/IS/CF mapping (xác nhận từ BVH thực tế)

db/
  migrations/
    014_financial_reports.sql       ← CREATE TABLE + indexes + CHECK constraints

tests/
  test_finance_parsers.py           ← Unit tests (mock DataFrame, 4 templates)
  test_finance_integration.py       ← Integration tests (API thực, staging DB)

jupyter_test/
  finance/
    balance_sheet_year.csv          ← Có (HPG, phi tài chính)
    income_statement_year.csv       ← Có (HPG, phi tài chính)
    cash_flow_year.csv              ← Có (HPG, phi tài chính)
    ratio_year.csv                  ← Có (HPG)
    banking_sample.ipynb            ← Cần tạo (VCB)
    securities_sample.ipynb         ← Cần tạo (SSI)
    insurance_sample.ipynb          ← Cần tạo (BVH)
```

### 5.5 Checklist trước khi go-live

```
[ ] Migration 014 đã chạy trên staging và production
[ ] Mapping dictionary đã được peer-review cho cả 4 template
[ ] Unit tests >= 90% branch coverage (đặc biệt: abs() cho chi phí, None cho null_fields)
[ ] Integration test pass với HPG, VCB, SSI, BVH
[ ] CHECK constraints đã VALIDATE trên toàn bộ dữ liệu staging
[ ] Screener endpoint EXPLAIN ANALYZE xác nhận index-only scan
[ ] pipeline_logs không có failure rate > 1% sau full run
[ ] raw_details endpoint trả đúng tên cột tiếng Việt
[ ] Cột isb*/cfb* xử lý nhất quán (không gây lỗi với non-financial)
```
