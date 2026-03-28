"""
Phase 3 Verification Script — Kiểm tra mapping stubs với dữ liệu thực tế.

Fetch BCTC từ VCI qua vnstock_data cho:
  - VCB  (Banking  — ICB 8300)
  - SSI  (Securities — ICB 8500)
  - BVH  (Insurance  — ICB 8400)

So sánh tên cột thực tế với mapping stubs, báo cáo:
  - Matched: cột API khớp với mapping key
  - Unmatched: cột API chưa có trong mapping (cần thêm?)
  - Dead keys: mapping key không xuất hiện trong API data (tên sai?)

Chạy: python scripts/verify_phase3_mappings.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from vnstock_data import Finance

from etl.transformers.mappings.banking    import (BALANCE_SHEET_MAP as BNK_BS,
                                                    INCOME_STATEMENT_MAP as BNK_IS,
                                                    CASH_FLOW_MAP as BNK_CF)
from etl.transformers.mappings.securities import (BALANCE_SHEET_MAP as SEC_BS,
                                                    INCOME_STATEMENT_MAP as SEC_IS,
                                                    CASH_FLOW_MAP as SEC_CF)
from etl.transformers.mappings.insurance  import (BALANCE_SHEET_MAP as INS_BS,
                                                    INCOME_STATEMENT_MAP as INS_IS,
                                                    CASH_FLOW_MAP as INS_CF)
from etl.transformers.mappings.non_financial import (BALANCE_SHEET_MAP as NF_BS,
                                                      INCOME_STATEMENT_MAP as NF_IS,
                                                      CASH_FLOW_MAP as NF_CF)

SYMBOLS = {
    "HPG": {"template": "non_financial", "maps": {"balance_sheet": NF_BS, "income_statement": NF_IS, "cash_flow": NF_CF}},
    "VCB": {"template": "banking",       "maps": {"balance_sheet": BNK_BS, "income_statement": BNK_IS, "cash_flow": BNK_CF}},
    "SSI": {"template": "securities",    "maps": {"balance_sheet": SEC_BS, "income_statement": SEC_IS, "cash_flow": SEC_CF}},
    "BVH": {"template": "insurance",     "maps": {"balance_sheet": INS_BS, "income_statement": INS_IS, "cash_flow": INS_CF}},
}

STMT_METHOD = {
    "balance_sheet":     "balance_sheet",
    "income_statement":  "income_statement",
    "cash_flow":         "cash_flow",
}

# Cột kỹ thuật không phải chỉ tiêu kế toán
SKIP_COLS = {
    "ticker", "report_period", "Năm", "Quý", "yearReport", "lengthReport",
}

def _get_columns(df: pd.DataFrame) -> list[str]:
    """Lấy danh sách tên cột thực sự là chỉ tiêu kế toán."""
    cols = []
    for c in df.columns:
        c_str = str(c).strip()
        if c_str in SKIP_COLS:
            continue
        # Bỏ cột mã thô dạng isb*, cfb*, bsb*
        if len(c_str) <= 6 and c_str[:3].lower() in ("isb", "cfb", "bsb", "rtb"):
            continue
        cols.append(c_str)
    return cols


def compare_mapping(symbol: str, stmt: str, df: pd.DataFrame, mapping: dict[str, str]) -> dict:
    api_cols = set(_get_columns(df))
    map_keys = set(mapping.keys())

    matched   = api_cols & map_keys
    unmatched = api_cols - map_keys   # cột API chưa trong mapping
    dead_keys = map_keys - api_cols   # mapping key không khớp API

    return {
        "symbol":    symbol,
        "stmt":      stmt,
        "api_cols":  sorted(api_cols),
        "matched":   sorted(matched),
        "unmatched": sorted(unmatched),
        "dead_keys": sorted(dead_keys),
        "match_pct": round(len(matched) / len(api_cols) * 100, 1) if api_cols else 0,
    }


def run_verification():
    all_results = []

    for symbol, info in SYMBOLS.items():
        template = info["template"]
        print(f"\n{'='*60}")
        print(f"  {symbol} ({template.upper()})")
        print(f"{'='*60}")

        try:
            fin = Finance(symbol=symbol, period="year", source="vci")
        except Exception as e:
            print(f"  [ERROR] Cannot init Finance for {symbol}: {e}")
            continue

        for stmt_key, map_dict in info["maps"].items():
            method_name = STMT_METHOD[stmt_key]
            try:
                df = getattr(fin, method_name)(lang="vi")
                if df is None or df.empty:
                    print(f"  [{stmt_key}] Empty DataFrame — skip")
                    continue
            except Exception as e:
                print(f"  [{stmt_key}] ERROR fetching: {e}")
                continue

            result = compare_mapping(symbol, stmt_key, df, map_dict)
            all_results.append(result)

            print(f"\n  [{stmt_key}] API cols: {len(result['api_cols'])} | "
                  f"Matched: {len(result['matched'])} | "
                  f"Unmatched: {len(result['unmatched'])} | "
                  f"Dead keys: {len(result['dead_keys'])} | "
                  f"Match%: {result['match_pct']}%")

            if result["matched"]:
                print(f"    [OK] Matched ({len(result['matched'])}):")
                for c in result["matched"]:
                    print(f"      '{c}' -> '{map_dict[c]}'")

            if result["unmatched"]:
                print(f"\n    [?] Unmatched API cols (chua co trong mapping):")
                for c in result["unmatched"]:
                    print(f"      '{c}'")

            if result["dead_keys"]:
                print(f"\n    [X] Dead mapping keys (ten sai - khong khop API):")
                for k in result["dead_keys"]:
                    print(f"      '{k}' -> '{map_dict[k]}'")

    # Summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    for r in all_results:
        status = "PASS" if r["match_pct"] >= 80 else ("WARN" if r["match_pct"] >= 50 else "FAIL")
        print(f"  [{status}] {r['symbol']:4s} {r['stmt']:20s} "
              f"match={r['match_pct']:5.1f}% "
              f"unmatched={len(r['unmatched'])} dead={len(r['dead_keys'])}")

    return all_results


if __name__ == "__main__":
    results = run_verification()
    any_fail = any(r["match_pct"] < 50 for r in results)
    sys.exit(1 if any_fail else 0)
