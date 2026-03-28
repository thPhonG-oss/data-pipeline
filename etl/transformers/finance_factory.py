"""
FinanceParserFactory — định tuyến parser dựa trên mã ICB.

Cách dùng:
    from etl.transformers.finance_factory import FinanceParserFactory

    parser = FinanceParserFactory.get_parser(icb_code="30101010", statement_type="balance_sheet")
    payloads = parser.parse(df_raw, symbol="VCB")

Quy tắc định tuyến (DB lưu ICB 8 chữ số theo chuẩn FTSE):
    icb_code bắt đầu bằng "3010"   → BankingParser        (30101010 = Banks)
    icb_code bắt đầu bằng "3030"   → InsuranceParser       (303010xx = Insurance)
    icb_code bắt đầu bằng "3020"   → SecuritiesParser      (30202xxx = Brokerage)
    icb_code bắt đầu bằng "30302"  → InsuranceParser       (30302xxx = Nonlife Insurance)
    Tất cả còn lại / None          → NonFinancialParser

Hỗ trợ legacy: mã cũ 4 ký tự "8300"/"8400"/"8500" (vnstock cũ) vẫn được nhận dạng.
"""
from __future__ import annotations

from etl.transformers.finance_parsers import (
    BaseFinancialParser,
    BankingParser,
    InsuranceParser,
    NonFinancialParser,
    SecuritiesParser,
)

_DEFAULT_PARSER: type[BaseFinancialParser] = NonFinancialParser


def _resolve_parser(icb_code: str | None) -> type[BaseFinancialParser]:
    """
    Xác định parser class từ icb_code.

    Hỗ trợ cả 2 định dạng:
      - 8 chữ số mới (FTSE): "30101010", "30301010", "30202015"...
      - Định dạng cũ 2-4 chữ số: "83", "8300", "84", "8400", "85", "8500"
    """
    code = (icb_code or "").strip()
    if not code:
        return _DEFAULT_PARSER

    # ── Định dạng FTSE 8 chữ số (DB hiện tại) ─────────────────────
    if code.startswith("3010"):    # 30101010 = Banks
        return BankingParser
    if code.startswith("3030"):    # 30301010 = Life Insurance
        return InsuranceParser
    if code.startswith("30302"):   # 30302010/20 = Nonlife/Reinsurance
        return InsuranceParser
    if code.startswith("3020"):    # 30202015 = Investment Services (CTCK)
        return SecuritiesParser

    # ── Định dạng cũ (legacy vnstock) ─────────────────────────────
    prefix2 = code[:2]
    if prefix2 == "83":
        return BankingParser
    if prefix2 == "84":
        return InsuranceParser
    if prefix2 == "85":
        return SecuritiesParser

    return _DEFAULT_PARSER


class FinanceParserFactory:
    """
    Xác định parser phù hợp cho doanh nghiệp dựa trên mã ICB.

    Tất cả mã ICB không được ánh xạ rõ ràng (hoặc None) → NonFinancialParser.
    Điều này đảm bảo pipeline không bị dừng khi icb_code chưa được resolve
    cho công ty mới niêm yết.
    """

    @staticmethod
    def get_parser(
        icb_code: str | None,
        statement_type: str,
    ) -> BaseFinancialParser:
        """
        Trả về parser instance tương ứng với icb_code và statement_type.

        Args:
            icb_code:       Mã ICB của công ty (8 chữ số FTSE hoặc legacy 2-4 chữ số).
                            None → fallback NonFinancialParser.
            statement_type: "balance_sheet" | "income_statement" | "cash_flow"

        Returns:
            Instance của parser đã được khởi tạo với statement_type.
        """
        parser_class = _resolve_parser(icb_code)
        return parser_class(statement_type=statement_type)

    @staticmethod
    def template_for_icb(icb_code: str | None) -> str:
        """
        Trả về tên template (fin_template_enum) tương ứng với icb_code.

        Hữu ích khi cần ghi template mà không cần khởi tạo parser.
        """
        parser_class = _resolve_parser(icb_code)
        return {
            BankingParser:      "banking",
            InsuranceParser:    "insurance",
            SecuritiesParser:   "securities",
            NonFinancialParser: "non_financial",
        }[parser_class]
