# Phase 7 — Mở rộng nguồn dữ liệu: Giá lịch sử & Cross-Validation BCTC

> **Cập nhật:** 2026-03-21 — Viết lại hoàn toàn sau khi xác nhận TCBS API đã bị đóng
> **Trạng thái:** Thiết kế chi tiết — sẵn sàng implement

---

## ⚠️ Đính chính quan trọng — TCBS API đã chết

Tài liệu `data_source_strategy.md` đề xuất TCBS làm nguồn ưu tiên. **Đề xuất đó không còn khả thi.**

### Điều gì đã xảy ra với TCBS?

| Thời điểm | Sự kiện |
|---|---|
| 2022–2023 | `apipubaws.tcbs.com.vn` hoạt động công khai, không cần auth — vnstock dùng làm nguồn chính |
| 2024 | TCBS bắt đầu siết dần — các endpoint dần trả lỗi, vnstock ghi trong CHANGELOG: *"Tạm thời không hoạt động do thay đổi API từ TCBS"* |
| Tháng 5/2025 | vnstock v3.2.5 vẫn còn patch bug TCBS (timezone, data type) — một số endpoint còn sống |
| **Tháng 3/2026 (v3.5.0)** | **TCBS bị xóa hoàn toàn khỏi vnstock** — CHANGELOG ghi rõ: *"Removed TCBS data source and all its related dependencies and integrations across the library (`explorer/tcbs/`)"* |

**Nguyên nhân:** TCBS đã yêu cầu JWT token / session cookie từ app TCInvest cho toàn bộ API. Không có chương trình developer public. Reverse-engineer session token vừa không ổn định vừa vi phạm ToS của TCBS.

**Kết luận: TCBS không thể dùng làm nguồn dữ liệu cho pipeline.**

---

## Mục lục

1. [Bức tranh toàn cảnh API chứng khoán Việt Nam hiện nay](#1-bức-tranh-toàn-cảnh-api-chứng-khoán-việt-nam-hiện-nay)
2. [Nguồn được chọn và lý do](#2-nguồn-được-chọn-và-lý-do)
3. [Tổng quan kiến trúc Phase 7](#3-tổng-quan-kiến-trúc-phase-7)
4. [Phase 7A — Giá lịch sử OHLCV (VNDirect)](#4-phase-7a--giá-lịch-sử-ohlcv-vndirect)
5. [Phase 7B — Cross-Validation BCTC (KBS vs VCI)](#5-phase-7b--cross-validation-bctc-kbs-vs-vci)
6. [Tích hợp vào hệ thống hiện có](#6-tích-hợp-vào-hệ-thống-hiện-có)
7. [Rủi ro và giảm thiểu](#7-rủi-ro-và-giảm-thiểu)
8. [Thứ tự implement](#8-thứ-tự-implement)

---

## 1. Bức tranh toàn cảnh API chứng khoán Việt Nam hiện nay

Sau khi nghiên cứu kỹ (tháng 3/2026), đây là thực trạng các nguồn dữ liệu:

| Nguồn | Auth | OHLCV | BCTC | Độ ổn định | Ghi chú |
|---|---|---|---|---|---|
| **VCI (Vietcap)** | Không cần | ✅ multi-timeframe | ✅ GraphQL | Tốt | Đang dùng trong pipeline (vnstock_data) |
| **KBS (KB Securities)** | Không cần | ✅ multi-timeframe | ✅ REST | **Tốt nhất** — default của vnstock từ v3.4.0 | Thay thế TCBS |
| **VNDirect finfo-api** | Không cần | ✅ daily OHLCV | ❌ | Tốt — public từ 2019 | Endpoint được cộng đồng ghi lại nhiều nhất |
| **DNSE** | ✅ Cần account | ✅ intraday tốt | ❌ | Tốt | Tốt nhất cho intraday, cần đăng ký |
| **SSI FastConnect** | ✅ Cần account | ✅ | ✅ | Chuyên nghiệp | API program chính thức |
| **FireAnt** | ✅ Trả phí | ✅ | ✅ | Xuất sắc | 5.4 triệu VND/năm |
| **FiinGroup** | ✅ Enterprise | ✅ | ✅ chuẩn IFRS | Gold standard | Giá enterprise |
| **TCBS** | ✅ Bắt buộc JWT | ❌ Đã xóa | ❌ Đã xóa | Không dùng được | Removed from vnstock v3.5.0 |
| **HOSE/HNX direct** | N/A | Không có API | Không có API | — | Không tồn tại API public |

### Điểm mấu chốt

> **VCI và KBS đều không cần authentication** — cả hai dùng browser-like headers (user-agent spoofing), là nội API nội bộ của các CTCK đang được truy cập không chính thức. Đây cũng là cách vnstock đang hoạt động với cả hai nguồn này từ trước đến nay.

---

## 2. Nguồn được chọn và lý do

### Phase 7A — Giá lịch sử OHLCV: **DNSE LightSpeed API**

```
PRIMARY:  DNSE     — qua vnstock Quote(source='DNSE')  [yêu cầu tài khoản DNSE]
FALLBACK: VNDirect — finfo-api.vndirect.com.vn/v4/stock_prices/  [public, không cần auth]
```

**Lý do chọn DNSE làm primary:**

| Tiêu chí | DNSE | VNDirect finfo-api |
|---|---|---|
| Chất lượng dữ liệu | Feed trực tiếp từ sàn — authoritative | Secondary aggregator |
| Lịch sử daily | 10 năm | Tương đương |
| Intraday | 1m, 1H, 1D, W (90 ngày) | Daily only |
| vnstock support | `Quote(source='DNSE')` — tích hợp đầy đủ | `source='VNDIRECT'` legacy |
| Auth | JWT 8h — cần DNSE account | Không cần |
| Real-time | WebSocket/MQTT | Không |
| Tài khoản | Người dùng đã có | N/A |

**Tại sao dùng vnstock thay vì HTTP client thủ công cho DNSE:**
- vnstock xử lý JWT token, refresh, retry nội bộ — không cần viết auth flow riêng
- Credentials (`DNSE_USERNAME`, `DNSE_PASSWORD`) truyền qua `.env`, vnstock tự đăng nhập
- Nếu DNSE đổi API, vnstock update — pipeline hưởng lợi

**VNDirect vẫn là fallback quan trọng** — public, không cần auth, ổn định từ 2019. Nếu DNSE gặp sự cố (token hết hạn, endpoint thay đổi), VNDirect là backup ngay lập tức.

### Phase 7B — Cross-Validation BCTC: **KBS vs VCI (qua vnstock)**

```
Nguồn A (trong DB): VCI — đang có sẵn trong balance_sheets, income_statements, ...
Nguồn B (fetch mới): KBS — qua vnstock Finance(source="kbs", symbol=...)
```

**Lý do dùng vnstock cho KBS thay vì viết HTTP riêng:**

Giai đoạn 7B là về **chất lượng dữ liệu**, không phải độc lập khỏi vnstock. KBS đã được vnstock tích hợp hoàn chỉnh, có retry, transform cơ bản. Viết lại HTTP từ đầu cho KBS để cross-validate là không cần thiết và thêm maintenance cost — nên dùng `Finance(source="kbs")` từ vnstock trực tiếp.

---

## 3. Tổng quan kiến trúc Phase 7

```
Hiện tại (Phase 1–6)                   Thêm vào (Phase 7)
────────────────────                   ──────────────────────────────────
etl/extractors/
  ├── listing.py  (vnstock/vnd)          ├── dnse_price.py       ← MỚI 7A (primary)
  ├── finance.py  (vnstock/vci)          ├── vndirect_price.py   ← MỚI 7A (fallback)
  ├── company.py  (vnstock/vci)          └── (kbs dùng qua vnstock)
  └── trading.py  (vnstock/vci)

etl/transformers/
  ├── listing.py                         ├── dnse_price.py       ← MỚI 7A (primary)
  ├── finance.py                         ├── vndirect_price.py   ← MỚI 7A (fallback)
  ├── company.py
  └── trading.py

etl/validators/                          ← MỚI 7B (thư mục mới)
                                         └── cross_source.py

jobs/
  ├── sync_listing.py                    ├── sync_prices.py      ← MỚI 7A
  ├── sync_financials.py (+ validator)   ← SỬA NHỎ 7B
  ├── sync_company.py
  └── sync_ratios.py

db/migrations/
  ├── 001–004 (giữ nguyên)              ├── 005_price_history.sql   ← MỚI 7A
                                         └── 006_data_quality.sql    ← MỚI 7B

config/constants.py                      ← thêm JOB_SYNC_PRICES
config/settings.py                       ← thêm cron_sync_prices, dnse_username, dnse_password
scheduler/jobs.py                        ← thêm sync_prices job
main.py                                  ← thêm sync_prices CLI
.env.example                             ← thêm CRON_SYNC_PRICES, DNSE_USERNAME, DNSE_PASSWORD
```

---

## 4. Phase 7A — Giá lịch sử OHLCV (DNSE + VNDirect fallback)

### 4.1 DNSE LightSpeed API — Tổng quan

DNSE cung cấp dữ liệu giá qua hai cơ chế:
- **WebSocket/MQTT** (MDDS): real-time streaming theo topic `plaintext/quotes/{type}/OHLC/{resolution}/{symbol}`
- **REST historical** (qua vnstock): `Quote(source='DNSE').history()`

Pipeline dùng REST historical qua **vnstock** — vnstock xử lý toàn bộ auth và HTTP.

#### Authentication flow (JWT)

```
POST https://services.entrade.com.vn/dnse-auth-service/login
Body: { "username": "<email/phone>", "password": "<password>" }
Response: { "token": "<JWT>", ... }      # Hết hạn sau 8 giờ
```

> **Pipeline không gọi trực tiếp endpoint này** — vnstock tự xử lý token khi dùng `source='DNSE'`.
> Credentials lưu trong `.env` dưới dạng `DNSE_USERNAME` / `DNSE_PASSWORD`.

#### Dữ liệu lịch sử qua vnstock

```python
from vnstock import Quote

df = Quote(symbol="HPG", source="DNSE").history(
    start="2020-01-01",
    end="2026-03-21",
    interval="1D",
)
```

**Các interval hỗ trợ:** `1` (1 phút), `1H` (1 giờ), `1D` (ngày), `W` (tuần)

**Giới hạn lịch sử:**
- Daily (1D): tối đa **10 năm**
- Intraday (1m, 1H): tối đa **90 ngày** gần nhất

**Columns vnstock trả về** (kiểm tra khi implement — có thể thay đổi theo phiên bản vnstock):

| Column vnstock | Ý nghĩa | Đơn vị |
|---|---|---|
| `time` | Ngày giao dịch | datetime |
| `open` | Giá mở cửa | VND (vnstock normalize sẵn) |
| `high` | Giá cao nhất | VND |
| `low` | Giá thấp nhất | VND |
| `close` | Giá đóng cửa | VND |
| `volume` | Khối lượng | Cổ phiếu |

> **Quan trọng — kiểm tra đơn vị giá khi implement:**
> vnstock có thể trả về VND nguyên (×1 giữ nguyên) hoặc nghìn VND (cần ×1000).
> Chạy thử `Quote('HPG', source='DNSE').history(start='2024-01-02', end='2024-01-02')` và kiểm tra giá HPG so với thực tế để xác định.
>
> **Lưu ý:** DNSE không trả về `adClose` (giá điều chỉnh) — cột `close_adj` trong DB sẽ NULL cho nguồn DNSE. VNDirect finfo-api có `adClose` — đây là lý do VNDirect vẫn là fallback có giá trị.

### 4.2 VNDirect finfo-api — Fallback

Dùng khi DNSE không khả dụng (token hết hạn, endpoint thay đổi, account bị khóa).

**Base URL:** `https://finfo-api.vndirect.com.vn`

```
GET /v4/stock_prices/
    ?sort=date
    &size=500
    &page=<trang>
    &q=code:<SYMBOL>~date:gte:<YYYY-MM-DD>~date:lte:<YYYY-MM-DD>
```

**Ví dụ:**
```
GET https://finfo-api.vndirect.com.vn/v4/stock_prices/
    ?sort=date&size=100&page=1
    &q=code:HPG~date:gte:2024-01-01~date:lte:2024-12-31
```

**Response fields:** `code`, `date`, `open`, `high`, `low`, `close`, `adClose`, `volume`, `nmVolume`, `value`

> **Đơn vị:** Nghìn VND — `27.5` = 27,500 đồng. Nhân ×1000 trước khi lưu vào DB.
>
> **Ưu điểm so với DNSE:** Có `adClose` (giá điều chỉnh cho cổ tức/tách cổ phiếu) — dùng lúc DNSE là primary thì `close_adj` sẽ bị NULL; nếu cần `close_adj`, dùng VNDirect.

**Headers:**
```python
{
    "Accept":     "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    "https://www.vndirect.com.vn/",
}
```

### 4.3 Migration — `db/migrations/005_price_history.sql`

```sql
-- ============================================================
-- Migration 005: Bảng giá lịch sử OHLCV
-- Nguồn chính:    DNSE LightSpeed API (qua vnstock Quote, feed trực tiếp từ sàn)
-- Nguồn dự phòng: VNDirect finfo-api (public, không cần auth)
--
-- Đơn vị lưu trữ: close/open/high/low = VND (đồng nguyên)
-- → DNSE qua vnstock: kiểm tra đơn vị khi implement (có thể đã normalize)
-- → VNDirect trả về nghìn VND → nhân ×1000 trước khi lưu
-- ============================================================

CREATE TABLE IF NOT EXISTS price_history (
    id          SERIAL       PRIMARY KEY,
    symbol      VARCHAR(10)  NOT NULL
        CONSTRAINT fk_ph_symbol REFERENCES companies(symbol),
    date        DATE         NOT NULL,

    open        INTEGER,          -- Giá mở cửa (VND)
    high        INTEGER,          -- Giá cao nhất trong phiên (VND)
    low         INTEGER,          -- Giá thấp nhất trong phiên (VND)
    close       INTEGER NOT NULL, -- Giá đóng cửa (VND)
    close_adj   INTEGER,          -- Giá đóng cửa điều chỉnh — dùng cho tính toán chỉ số (VND)
    volume      BIGINT,           -- Khối lượng khớp lệnh thỏa thuận + tự doanh (cổ phiếu)
    volume_nm   BIGINT,           -- Khối lượng khớp lệnh thông thường (VNDirect: nmVolume)
    value       BIGINT,           -- Giá trị giao dịch (triệu VND)

    source      VARCHAR(20)  DEFAULT 'dnse',
    fetched_at  TIMESTAMP    DEFAULT NOW(),

    CONSTRAINT uq_price_history UNIQUE (symbol, date, source)
);

CREATE INDEX IF NOT EXISTS idx_ph_symbol   ON price_history(symbol);
CREATE INDEX IF NOT EXISTS idx_ph_date     ON price_history(date DESC);
CREATE INDEX IF NOT EXISTS idx_ph_sym_date ON price_history(symbol, date DESC);

COMMENT ON TABLE price_history IS
    'Giá lịch sử OHLCV theo ngày. '
    'Nguồn chính: DNSE LightSpeed API qua vnstock Quote(source=DNSE) — feed trực tiếp từ sàn. '
    'Nguồn dự phòng: VNDirect finfo-api (public, không cần auth). '
    'close_adj = NULL khi source=dnse (DNSE không cung cấp adjusted close). '
    'Đơn vị: close/open/high/low/close_adj = VND nguyên.';

COMMENT ON COLUMN price_history.close_adj IS
    'Giá đóng cửa đã điều chỉnh — dùng để tính P/E, P/B, return chính xác khi có sự kiện cổ tức, tách cổ phiếu.';
COMMENT ON COLUMN price_history.value IS
    'Giá trị giao dịch, đơn vị triệu VND.';
```

### 4.4 Extractor (Primary) — `etl/extractors/dnse_price.py`

```python
"""
Extractor lấy giá lịch sử OHLCV từ DNSE qua vnstock Quote(source='DNSE').

Ưu điểm so với HTTP client thủ công:
  - vnstock xử lý JWT token, refresh, retry nội bộ
  - Không cần maintain HTTP client riêng cho DNSE
  - Dễ nâng cấp intraday sau này (đổi interval='1' hoặc '1H')

Credentials DNSE: lưu trong .env dưới dạng DNSE_USERNAME / DNSE_PASSWORD.
vnstock tự đọc credentials khi khởi tạo (kiểm tra cơ chế inject của vnstock khi implement).

Lịch sử hỗ trợ: daily tối đa 10 năm, intraday tối đa 90 ngày.
"""
from datetime import date

import pandas as pd

from etl.base.extractor import BaseExtractor
from utils.logger import logger

_YEARS_DEFAULT = 5   # Số năm lấy khi không có dữ liệu trong DB


class DNSEPriceExtractor(BaseExtractor):
    """
    Lấy giá lịch sử OHLCV từ DNSE qua vnstock.
    vnstock xử lý authentication JWT (8h token) nội bộ.
    """

    def __init__(self) -> None:
        super().__init__(source="dnse")

    def extract(self, symbol: str, **kwargs) -> pd.DataFrame | None:
        """Alias cho extract_price_history() — tương thích BaseExtractor."""
        return self.extract_price_history(
            symbol,
            start=kwargs.get("start"),
            end=kwargs.get("end"),
        )

    def extract_price_history(
        self,
        symbol: str,
        start:  date | None = None,
        end:    date | None = None,
        interval: str = "1D",
    ) -> pd.DataFrame | None:
        """
        Lấy lịch sử giá OHLCV từ DNSE qua vnstock.

        Args:
            symbol:   Mã chứng khoán (ví dụ: "HPG").
            start:    Từ ngày. None = _YEARS_DEFAULT năm gần nhất.
            end:      Đến ngày. None = hôm nay.
            interval: '1D' (ngày), '1H' (giờ), '1' (1 phút), 'W' (tuần).

        Returns:
            DataFrame từ vnstock, hoặc None nếu không có dữ liệu.
        """
        if end is None:
            end = date.today()
        if start is None:
            start = end.replace(year=end.year - _YEARS_DEFAULT)

        try:
            from vnstock import Quote
            df = Quote(symbol=symbol.upper(), source="DNSE").history(
                start=str(start),
                end=str(end),
                interval=interval,
            )
        except Exception as exc:
            logger.error(f"[dnse_price] {symbol}: lỗi khi fetch: {exc}")
            raise   # Re-raise để sync_prices có thể bắt và thử fallback VNDirect

        if df is None or df.empty:
            logger.warning(f"[dnse_price] {symbol}: vnstock trả về rỗng ({start} → {end}).")
            return None

        logger.info(f"[dnse_price] {symbol}: {len(df)} phiên ({start} → {end}).")
        return df
```

### 4.5 Extractor (Fallback) — `etl/extractors/vndirect_price.py`

```python
"""
Extractor lấy giá lịch sử OHLCV từ VNDirect finfo-api.

Dùng làm FALLBACK khi DNSE không khả dụng.
Public API — không cần authentication. Ổn định từ 2019.
Đơn vị giá trả về: nghìn VND (×1000 để ra VND nguyên).
Có adClose (adjusted close) — ưu điểm so với DNSE.
"""
import math
from datetime import date

import pandas as pd
import requests

from etl.base.extractor import BaseExtractor
from utils.logger import logger
from utils.retry import vnstock_retry

_BASE_URL  = "https://finfo-api.vndirect.com.vn"
_HEADERS   = {
    "Accept":     "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    "https://www.vndirect.com.vn/",
}
_PAGE_SIZE = 500


class VNDirectPriceExtractor(BaseExtractor):
    """Lấy giá lịch sử OHLCV từ VNDirect finfo-api (fallback cho DNSE)."""

    def __init__(self) -> None:
        super().__init__(source="vndirect")

    def extract(self, symbol: str, **kwargs) -> pd.DataFrame | None:
        return self.extract_price_history(symbol, start=kwargs.get("start"), end=kwargs.get("end"))

    def extract_price_history(
        self, symbol: str, start: date | None = None, end: date | None = None
    ) -> pd.DataFrame | None:
        if end is None:
            end = date.today()
        if start is None:
            start = end.replace(year=end.year - 5)

        all_records: list[dict] = []
        page = 1
        while True:
            batch = self._fetch_page(symbol, start, end, page)
            if not batch:
                break
            all_records.extend(batch)
            if len(batch) < _PAGE_SIZE:
                break
            page += 1

        if not all_records:
            logger.warning(f"[vndirect_price] {symbol}: API trả về rỗng ({start} → {end}).")
            return None

        df = pd.DataFrame(all_records)
        logger.info(f"[vndirect_price] {symbol}: {len(df)} phiên ({start} → {end}).")
        return df

    @vnstock_retry()
    def _fetch_page(self, symbol: str, start: date, end: date, page: int) -> list[dict]:
        params = {
            "sort": "date", "size": _PAGE_SIZE, "page": page,
            "q": f"code:{symbol.upper()}~date:gte:{start}~date:lte:{end}",
        }
        resp = requests.get(f"{_BASE_URL}/v4/stock_prices/",
                            params=params, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json().get("data", [])
```

### 4.6 Transformer (Primary) — `etl/transformers/dnse_price.py`

```python
"""
Transformer chuẩn hóa giá từ DNSE (qua vnstock) → schema bảng price_history.

vnstock Quote(source='DNSE').history() trả về DataFrame với columns:
  time  → date       (datetime → date)
  open  → open       (INTEGER VND — xác nhận đơn vị khi implement)
  high  → high       (INTEGER VND)
  low   → low        (INTEGER VND)
  close → close      (INTEGER VND)
  volume → volume    (BIGINT)

Lưu ý:
  - DNSE KHÔNG có adjusted close → close_adj = NULL
  - Nếu vnstock trả về giá dạng nghìn VND: cần nhân ×1000 (bật _NEEDS_SCALE = True)
  - Nếu vnstock đã normalize về VND nguyên: giữ nguyên (_NEEDS_SCALE = False)
  Kiểm tra bằng: Quote('HPG', source='DNSE').history(start='2024-01-02', end='2024-01-02')
  và so sánh với giá thực tế HPG ngày 2024-01-02.
"""
import math
from datetime import datetime, timezone

import pandas as pd

from etl.base.transformer import BaseTransformer
from utils.logger import logger

# TODO: Kiểm tra khi implement — set True nếu vnstock DNSE trả về nghìn VND
_NEEDS_SCALE = False   # Mặc định: giả sử vnstock đã normalize về VND nguyên


def _to_int(val, scale: int = 1) -> int | None:
    if val is None:
        return None
    try:
        f = float(val) * scale
        return None if (math.isnan(f) or math.isinf(f)) else int(round(f))
    except (TypeError, ValueError):
        return None


class DNSEPriceTransformer(BaseTransformer):
    """
    Chuyển DataFrame từ DNSEPriceExtractor → schema price_history.

    Column mapping (vnstock DNSE output → price_history):
      time   → date
      open   → open
      high   → high
      low    → low
      close  → close
      volume → volume
      (không có adClose → close_adj = NULL)
    """

    def transform(self, df: pd.DataFrame, symbol: str, **context) -> pd.DataFrame:
        df = df.copy()
        price_scale = 1000 if _NEEDS_SCALE else 1

        # 1. Metadata
        df["symbol"]     = symbol.upper()
        df["source"]     = "dnse"
        df["fetched_at"] = datetime.now(tz=timezone.utc)

        # 2. Ngày giao dịch — vnstock DNSE trả về cột 'time'
        date_col = "time" if "time" in df.columns else "date"
        df["date"] = pd.to_datetime(df[date_col]).dt.date

        # 3. Giá
        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df[col] = df[col].apply(lambda v: _to_int(v, price_scale))

        # 4. close_adj = NULL (DNSE không cung cấp adjusted close)
        df["close_adj"] = None

        # 5. Khối lượng
        if "volume" in df.columns:
            df["volume"] = df["volume"].apply(lambda v: _to_int(v))

        # 6. Bỏ dòng thiếu conflict key
        df = df.dropna(subset=["symbol", "date", "close"])
        df = df.drop_duplicates(subset=["symbol", "date", "source"], keep="last")

        # 7. Chỉ giữ cột DB
        _DB_COLS = [
            "symbol", "date", "open", "high", "low",
            "close", "close_adj", "volume", "source", "fetched_at",
        ]
        final_cols = [c for c in _DB_COLS if c in df.columns]
        df = df[final_cols]

        logger.info(f"[dnse_price] {symbol}: {len(df)} phiên sau transform.")
        return df.reset_index(drop=True)
```

### 4.7 Transformer (Fallback) — `etl/transformers/vndirect_price.py`

```python
"""
Transformer chuẩn hóa giá từ VNDirect → schema bảng price_history.
Dùng làm fallback khi DNSE không khả dụng.

Chuyển đổi:
  open/high/low/close/adClose: nghìn VND → VND nguyên (×1000)
  volume, nmVolume, value: giữ nguyên
"""
import math
from datetime import datetime, timezone

import pandas as pd

from etl.base.transformer import BaseTransformer
from utils.logger import logger


def _to_vnd(val) -> int | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else int(round(f * 1000))
    except (TypeError, ValueError):
        return None


def _to_bigint(val) -> int | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else int(f)
    except (TypeError, ValueError):
        return None


class VNDirectPriceTransformer(BaseTransformer):
    """
    Chuyển DataFrame từ VNDirectPriceExtractor → schema price_history.

    VNDirect → price_history:
      code/date → symbol/date
      open/high/low/close (nghìn VND) → ×1000 → INTEGER VND
      adClose → close_adj (có giá trị — ưu điểm so với DNSE)
      volume/nmVolume → volume/volume_nm
      value → value (triệu VND)
    """

    def transform(self, df: pd.DataFrame, symbol: str, **context) -> pd.DataFrame:
        df = df.copy()
        df["symbol"]     = symbol.upper()
        df["source"]     = "vndirect"
        df["fetched_at"] = datetime.now(tz=timezone.utc)
        df["date"]       = pd.to_datetime(df["date"]).dt.date

        for api_col, db_col in [
            ("open", "open"), ("high", "high"), ("low", "low"),
            ("close", "close"), ("adClose", "close_adj"),
        ]:
            if api_col in df.columns:
                df[db_col] = df[api_col].apply(_to_vnd)

        if "volume" in df.columns:
            df["volume"] = df["volume"].apply(_to_bigint)
        if "nmVolume" in df.columns:
            df["volume_nm"] = df["nmVolume"].apply(_to_bigint)
        if "value" in df.columns:
            df["value"] = df["value"].apply(_to_bigint)

        df = df.dropna(subset=["symbol", "date", "close"])
        df = df.drop_duplicates(subset=["symbol", "date", "source"], keep="last")

        _DB_COLS = [
            "symbol", "date", "open", "high", "low",
            "close", "close_adj", "volume", "volume_nm", "value",
            "source", "fetched_at",
        ]
        df = df[[c for c in _DB_COLS if c in df.columns]]
        logger.info(f"[vndirect_price] {symbol}: {len(df)} phiên sau transform.")
        return df.reset_index(drop=True)
```

### 4.8 Job — `jobs/sync_prices.py`

```python
"""
Job đồng bộ giá lịch sử OHLCV vào price_history.

Nguồn chính: DNSE (qua vnstock Quote) — feed từ sàn, cần DNSE account.
Fallback:    VNDirect finfo-api — public, không cần auth, có adClose.

Chiến lược incremental: mỗi lần chạy chỉ lấy từ ngày sau ngày cuối trong DB.
Full history (--full-history): lấy lại toàn bộ _YEARS_HISTORY năm.
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

from sqlalchemy import text

from config.constants import JOB_SYNC_PRICES
from config.settings import settings
from db.connection import engine
from etl.extractors.dnse_price import DNSEPriceExtractor
from etl.extractors.vndirect_price import VNDirectPriceExtractor
from etl.loaders.postgres import PostgresLoader
from etl.transformers.dnse_price import DNSEPriceTransformer
from etl.transformers.vndirect_price import VNDirectPriceTransformer
from utils.logger import logger

_CONFLICT_KEYS = ["symbol", "date", "source"]
_YEARS_HISTORY = 5   # Số năm lịch sử khi full_history=True


def _get_listed_symbols() -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT symbol FROM companies "
                 "WHERE status = 'listed' AND type = 'STOCK' ORDER BY symbol")
        ).fetchall()
    return [r[0] for r in rows]


def _get_last_date(symbol: str) -> date | None:
    """Ngày cuối cùng đã có dữ liệu giá của symbol trong DB (bất kỳ source)."""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT MAX(date) FROM price_history WHERE symbol = :sym"),
            {"sym": symbol},
        ).fetchone()
    return row[0] if row and row[0] else None


def _run_one(
    symbol:      str,
    extractor:   DNSEPriceExtractor,
    transformer: DNSEPriceTransformer,
    loader:      PostgresLoader,
    start:       date | None,
    end:         date,
) -> dict:
    log_id = loader.load_log(job_name=JOB_SYNC_PRICES, symbol=symbol, status="running")
    try:
        # Thử DNSE trước, fallback về VNDirect nếu DNSE lỗi
        try:
            df_raw = extractor.extract_price_history(symbol, start=start, end=end)
            tf = transformer
        except Exception as dnse_exc:
            logger.warning(f"[sync_prices] {symbol}: DNSE lỗi ({dnse_exc}), thử VNDirect...")
            df_raw = VNDirectPriceExtractor().extract_price_history(symbol, start=start, end=end)
            tf = VNDirectPriceTransformer()

        time.sleep(settings.request_delay)

        if df_raw is None or df_raw.empty:
            loader.load_log(job_name=JOB_SYNC_PRICES, symbol=symbol,
                            status="skipped", log_id=log_id)
            return {"symbol": symbol, "status": "skipped", "rows": 0}

        df = tf.transform(df_raw, symbol)

        if df.empty:
            loader.load_log(job_name=JOB_SYNC_PRICES, symbol=symbol,
                            status="skipped", log_id=log_id)
            return {"symbol": symbol, "status": "skipped", "rows": 0}

        rows = loader.load(df, "price_history", _CONFLICT_KEYS)
        loader.load_log(
            job_name=JOB_SYNC_PRICES, symbol=symbol,
            status="success", records_fetched=len(df),
            records_inserted=rows, log_id=log_id,
        )
        return {"symbol": symbol, "status": "success", "rows": rows}

    except Exception as exc:
        logger.error(f"[sync_prices] {symbol} lỗi: {exc}")
        loader.load_log(
            job_name=JOB_SYNC_PRICES, symbol=symbol,
            status="failed", error_message=str(exc)[:500], log_id=log_id,
        )
        return {"symbol": symbol, "status": "failed", "rows": 0}


def run(
    symbols:      list[str] | None = None,
    max_workers:  int | None = None,
    start:        date | None = None,
    end:          date | None = None,
    full_history: bool = False,
) -> dict:
    """
    Đồng bộ giá lịch sử từ VNDirect vào price_history.

    Args:
        symbols:      None = tất cả STOCK đang niêm yết.
        max_workers:  None = settings.max_workers.
        start:        None = incremental từ ngày cuối cùng trong DB.
        end:          None = hôm nay.
        full_history: True = lấy lại toàn bộ _YEARS_HISTORY năm cho tất cả mã.
    """
    symbols     = symbols or _get_listed_symbols()
    max_workers = max_workers or settings.max_workers
    end         = end or date.today()

    logger.info(
        f"[sync_prices] Bắt đầu: {len(symbols)} mã ({max_workers} luồng) | "
        f"full_history={full_history} | end={end}"
    )

    extractor   = DNSEPriceExtractor()
    transformer = DNSEPriceTransformer()
    loader      = PostgresLoader()
    totals      = {"success": 0, "failed": 0, "skipped": 0, "rows": 0}

    def _resolve_start(sym: str) -> date | None:
        if full_history:
            return end.replace(year=end.year - _YEARS_HISTORY)
        if start is not None:
            return start
        last = _get_last_date(sym)
        if last is None:
            return end.replace(year=end.year - _YEARS_HISTORY)   # Lần đầu: lấy 5 năm
        if last >= end:
            return None   # Đã có đến hôm nay → skip (trả về None để _run_one bỏ qua)
        return last + timedelta(days=1)   # Incremental: ngày hôm sau

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _run_one, sym, extractor, transformer, loader,
                _resolve_start(sym), end,
            ): sym
            for sym in symbols
        }
        for future in as_completed(futures):
            result = future.result()
            totals[result["status"]] += 1
            totals["rows"] += result["rows"]

    logger.info(
        f"[sync_prices] Xong. "
        f"Success={totals['success']} | Failed={totals['failed']} | "
        f"Skipped={totals['skipped']} | Rows={totals['rows']}"
    )
    return totals
```

### 4.10 Cập nhật các file hiện có

#### `config/constants.py` — thêm:
```python
JOB_SYNC_PRICES = "sync_prices"

ALL_JOBS = [..., JOB_SYNC_PRICES, ...]

CONFLICT_KEYS["price_history"] = ["symbol", "date", "source"]
```

#### `config/settings.py` — thêm:
```python
# ── DNSE ──────────────────────────────────────────────────
dnse_username: str = ""    # Email/SĐT đăng nhập DNSE
dnse_password: str = ""    # Mật khẩu DNSE

# ── Scheduler ─────────────────────────────────────────────
cron_sync_prices: str = "0 19 * * 1-5"   # Thứ Hai–Sáu 19:00
```

> Kiểm tra cơ chế vnstock inject DNSE credentials khi implement — có thể cần pass trực tiếp
> vào `Quote(source='DNSE', username=..., password=...)` thay vì chỉ lưu env var.

#### `scheduler/jobs.py` — thêm:
```python
import jobs.sync_prices as prices_job

scheduler.add_job(
    _safe_run(prices_job.run, "sync_prices"),
    CronTrigger.from_crontab(settings.cron_sync_prices, timezone="Asia/Ho_Chi_Minh"),
    id="sync_prices",
    name="Đồng bộ giá lịch sử OHLCV (DNSE primary, VNDirect fallback)",
    misfire_grace_time=3600,
)
```

#### `main.py` — thêm CLI command:
```python
p_prices = subparsers.add_parser(
    "sync_prices",
    help="Đồng bộ giá lịch sử OHLCV (DNSE primary, VNDirect fallback)",
)
p_prices.add_argument("--symbol", nargs="+", metavar="SYM")
p_prices.add_argument("--workers", type=int, metavar="N")
p_prices.add_argument("--start",  metavar="YYYY-MM-DD",
                      help="Từ ngày. Mặc định: incremental từ ngày cuối trong DB.")
p_prices.add_argument("--end",    metavar="YYYY-MM-DD",
                      help="Đến ngày. Mặc định: hôm nay.")
p_prices.add_argument("--full-history", action="store_true",
                      help="Lấy lại toàn bộ 5 năm bất kể DB đã có gì.")

# Trong main():
elif args.command == "sync_prices":
    from jobs.sync_prices import run
    from datetime import date as _date
    symbols = [s.upper() for s in args.symbol] if args.symbol else None
    start   = _date.fromisoformat(args.start) if args.start else None
    end     = _date.fromisoformat(args.end)   if args.end   else None
    result  = run(symbols=symbols, max_workers=args.workers,
                  start=start, end=end, full_history=args.full_history)
    logger.info(f"Kết quả: {result}")
```

#### `.env.example` — thêm:
```env
# ── DNSE ──────────────────────────────────────────────────────────────────────
DNSE_USERNAME=your_email_or_phone
DNSE_PASSWORD=your_dnse_password

# ── Scheduler ─────────────────────────────────────────────────────────────────
CRON_SYNC_PRICES="0 19 * * 1-5"    # Thứ Hai–Sáu 19:00 (sau đóng cửa 15:00 + buffer)
```

### 4.8 Lệnh chạy

```bash
# Initial load: lấy toàn bộ 5 năm lịch sử (~45–90 phút)
python main.py sync_prices --full-history

# Test nhanh với 3 mã
python main.py sync_prices --symbol HPG VCB FPT --full-history

# Incremental hàng ngày (scheduler tự chạy lúc 19:00)
python main.py sync_prices

# Sync khoảng thời gian cụ thể
python main.py sync_prices --start 2024-01-01 --end 2024-12-31

# Kiểm tra kết quả
docker compose exec postgres psql -U postgres -d stockapp -c "
SELECT symbol, MIN(date) AS từ_ngày, MAX(date) AS đến_ngày, COUNT(*) AS số_phiên
FROM price_history
GROUP BY symbol
ORDER BY symbol
LIMIT 20;"
```

---

## 5. Phase 7B — Cross-Validation BCTC (KBS vs VCI)

### 5.1 Thiết kế tổng thể

Pipeline hiện tại lưu BCTC từ VCI (vnstock_data.Finance source="vci"). Giai đoạn này so sánh các giá trị chủ chốt với KBS — nguồn mặc định hiện tại của vnstock, độc lập với VCI.

```
                   sync_financials chạy xong
                           │
                           ▼
               FinanceCrossValidator.validate(symbol)
                           │
               ┌───────────┴────────────┐
               ▼                        ▼
    Đọc VCI từ DB              Fetch KBS qua vnstock
    (balance_sheets,           Finance(source="kbs", symbol=...)
     income_statements, ...)   .balance_sheet()
               │                        │
               └────────── so sánh ─────┘
                           │
                 diff > 2% → ghi flag
                           │
                           ▼
                  data_quality_flags
```

**Lý do dùng vnstock cho KBS thay vì HTTP thủ công:**
- KBS đã được vnstock tích hợp hoàn chỉnh, có retry, header management
- Mục tiêu là **chất lượng dữ liệu**, không phải viết thêm HTTP client
- Tránh duplicate maintenance: nếu KBS đổi endpoint, vnstock update — pipeline hưởng lợi

### 5.2 Migration — `db/migrations/006_data_quality.sql`

```sql
-- ============================================================
-- Migration 006: Bảng data quality flags
-- Ghi lại khi VCI và KBS báo cáo số liệu khác nhau > 2%
-- ============================================================

CREATE TABLE IF NOT EXISTS data_quality_flags (
    id           SERIAL       PRIMARY KEY,
    symbol       VARCHAR(10)  NOT NULL,
    table_name   VARCHAR(50)  NOT NULL,
    period       VARCHAR(10)  NOT NULL,
    column_name  VARCHAR(100) NOT NULL,
    source_a     VARCHAR(20)  NOT NULL,   -- 'vci'
    value_a      NUMERIC(25, 4),
    source_b     VARCHAR(20)  NOT NULL,   -- 'kbs'
    value_b      NUMERIC(25, 4),
    diff_pct     NUMERIC(10, 4),          -- Tỷ lệ chênh lệch (%)
    flagged_at   TIMESTAMP    DEFAULT NOW(),
    resolved     BOOLEAN      DEFAULT FALSE,
    resolved_at  TIMESTAMP,
    notes        TEXT,

    CONSTRAINT uq_dq_flag UNIQUE (symbol, table_name, period, column_name, source_a, source_b)
);

CREATE INDEX IF NOT EXISTS idx_dq_symbol     ON data_quality_flags(symbol);
CREATE INDEX IF NOT EXISTS idx_dq_unresolved ON data_quality_flags(resolved) WHERE resolved = FALSE;
CREATE INDEX IF NOT EXISTS idx_dq_flagged_at ON data_quality_flags(flagged_at DESC);

COMMENT ON TABLE data_quality_flags IS
    'Dị thường khi cross-validate BCTC giữa VCI (nguồn chính, đang trong DB) '
    'và KBS (nguồn thứ 2, fetch qua vnstock). '
    'diff_pct = |VCI - KBS| / |VCI| × 100. Flag khi diff_pct > 2%.';
```

### 5.3 Cross-Validator — `etl/validators/__init__.py`

```python
# File rỗng — đánh dấu validators là Python package
```

### 5.4 Cross-Validator — `etl/validators/cross_source.py`

```python
"""
Cross-source validator: So sánh BCTC VCI (trong DB) với KBS (fetch qua vnstock).
Ghi flag vào data_quality_flags khi chênh lệch > DIFF_THRESHOLD.

Đơn vị:
  VCI lưu trong DB: tỷ VND (×10^9)
  KBS qua vnstock:  tỷ VND (đã được vnstock normalize)
  → So sánh trực tiếp, không cần quy đổi thêm.
"""
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text

from db.connection import engine
from etl.loaders.postgres import PostgresLoader
from utils.logger import logger

_DIFF_THRESHOLD = 0.02   # 2%

# Cột so sánh: db_column_name → tên cột KBS sau khi vnstock transform
# Chỉ so sánh các cột tổng hợp lớn — ít bị ảnh hưởng bởi phương pháp kế toán khác nhau
_BALANCE_SHEET_COLS = {
    "total_assets":        "total_assets",
    "total_equity":        "total_equity",
    "total_liabilities":   "total_liabilities",
}

_INCOME_STMT_COLS = {
    "net_revenue":  "net_revenue",
    "gross_profit": "gross_profit",
    "net_profit":   "net_profit",
}

_CASHFLOW_COLS = {
    "operating_cash_flow": "operating_cash_flow",
}

_TABLE_COLS_MAP = {
    "balance_sheets":    _BALANCE_SHEET_COLS,
    "income_statements": _INCOME_STMT_COLS,
    "cash_flows":        _CASHFLOW_COLS,
}

_REPORT_TYPE_MAP = {
    "balance_sheets":    "balance_sheet",
    "income_statements": "income_statement",
    "cash_flows":        "cash_flow",
}


class FinanceCrossValidator:
    """
    Validate BCTC cho 1 symbol: so sánh VCI (DB) với KBS (vnstock).
    Trả về số flags đã ghi.
    """

    def __init__(self) -> None:
        self._loader = PostgresLoader()

    def validate_symbol(self, symbol: str) -> int:
        """Chạy cross-validate cho tất cả loại BCTC của 1 symbol."""
        total = 0
        for table_name, col_map in _TABLE_COLS_MAP.items():
            total += self._validate_table(symbol, table_name, col_map)
        return total

    def _validate_table(self, symbol: str, table_name: str, col_map: dict) -> int:
        # Lấy VCI từ DB (3 năm gần nhất)
        df_vci = self._fetch_vci(symbol, table_name)
        if df_vci is None or df_vci.empty:
            return 0

        # Lấy KBS từ vnstock
        df_kbs = self._fetch_kbs(symbol, _REPORT_TYPE_MAP[table_name])
        if df_kbs is None or df_kbs.empty:
            return 0

        return self._compare_and_flag(symbol, table_name, df_vci, df_kbs, col_map)

    def _fetch_vci(self, symbol: str, table: str) -> pd.DataFrame | None:
        with engine.connect() as conn:
            rows = conn.execute(
                text(f"""
                    SELECT * FROM {table}
                    WHERE symbol = :sym AND period_type = 'year' AND source = 'vci'
                    ORDER BY period DESC LIMIT 3
                """),
                {"sym": symbol},
            ).fetchall()
        if not rows:
            return None
        return pd.DataFrame(rows, columns=rows[0]._fields)

    def _fetch_kbs(self, symbol: str, report_type: str) -> pd.DataFrame | None:
        """Lấy BCTC từ KBS qua vnstock (đã được normalize sẵn)."""
        try:
            from vnstock_data import Finance
            df = Finance(source="kbs", symbol=symbol, period="year") \
                     .__getattribute__(report_type)(lang="en")
            return df if df is not None and not df.empty else None
        except Exception as exc:
            logger.warning(f"[cross_validate] {symbol} KBS fetch lỗi: {exc}")
            return None

    def _compare_and_flag(
        self,
        symbol:     str,
        table_name: str,
        df_vci:     pd.DataFrame,
        df_kbs:     pd.DataFrame,
        col_map:    dict,
    ) -> int:
        flags = []
        now   = datetime.now(tz=timezone.utc)

        for _, vci_row in df_vci.iterrows():
            period = str(vci_row.get("period", ""))
            if len(period) != 4:   # Chỉ so sánh năm, không so sánh quý
                continue
            try:
                year = int(period)
            except ValueError:
                continue

            # Tìm dòng KBS tương ứng
            kbs_rows = df_kbs[df_kbs.index == year] if year in df_kbs.index else pd.DataFrame()
            if kbs_rows.empty:
                # Thử match theo cột year nếu có
                if "year" in df_kbs.columns:
                    kbs_rows = df_kbs[df_kbs["year"] == year]
            if kbs_rows.empty:
                continue
            kbs_row = kbs_rows.iloc[0]

            for db_col, kbs_col in col_map.items():
                if db_col not in df_vci.columns or kbs_col not in df_kbs.columns:
                    continue

                v_vci = vci_row.get(db_col)
                v_kbs = kbs_row.get(kbs_col)

                if v_vci is None or v_kbs is None:
                    continue

                try:
                    v = float(v_vci)
                    k = float(v_kbs)
                except (TypeError, ValueError):
                    continue

                if v == 0:
                    continue

                diff_pct = abs(v - k) / abs(v)
                if diff_pct > _DIFF_THRESHOLD:
                    flags.append({
                        "symbol":      symbol,
                        "table_name":  table_name,
                        "period":      period,
                        "column_name": db_col,
                        "source_a":    "vci",
                        "value_a":     round(v, 4),
                        "source_b":    "kbs",
                        "value_b":     round(k, 4),
                        "diff_pct":    round(diff_pct * 100, 4),
                        "flagged_at":  now,
                    })

        if not flags:
            return 0

        df_flags = pd.DataFrame(flags)
        self._loader.load(
            df_flags,
            table="data_quality_flags",
            conflict_columns=["symbol", "table_name", "period",
                               "column_name", "source_a", "source_b"],
        )
        logger.warning(
            f"[cross_validate] {symbol}/{table_name}: {len(flags)} flags "
            f"(chênh > {_DIFF_THRESHOLD:.0%})"
        )
        return len(flags)
```

### 5.5 Tích hợp vào `jobs/sync_financials.py`

Trong hàm `_run_one()`, sau khi `loader.load()` thành công, thêm:

```python
# Sau khi đã load xong tất cả 4 loại BCTC cho symbol
# (chạy 1 lần cuối, không chạy sau mỗi report_type)
if all_report_types_done:
    try:
        from etl.validators.cross_source import FinanceCrossValidator
        flags = FinanceCrossValidator().validate_symbol(symbol)
        if flags > 0:
            logger.warning(f"[sync_financials] {symbol}: {flags} data quality flags. "
                           f"Xem bảng data_quality_flags.")
    except Exception as exc:
        # Validate lỗi KHÔNG được làm hỏng sync chính
        logger.debug(f"[sync_financials] {symbol}: cross-validate bỏ qua: {exc}")
```

### 5.6 Query theo dõi và xử lý flags

```sql
-- Xem flags chưa xử lý, sắp xếp theo mức chênh lệch
SELECT symbol, table_name, period, column_name,
       ROUND(value_a/1e9, 2) AS vci_tỷ_vnd,
       ROUND(value_b/1e9, 2) AS kbs_tỷ_vnd,
       diff_pct               AS chênh_pct,
       flagged_at
FROM data_quality_flags
WHERE resolved = FALSE
ORDER BY diff_pct DESC, flagged_at DESC
LIMIT 30;

-- Mã nào có dữ liệu nghi ngờ nhất
SELECT symbol, COUNT(*) AS số_flag, ROUND(AVG(diff_pct), 1) AS chênh_tb_pct
FROM data_quality_flags
WHERE resolved = FALSE
GROUP BY symbol
ORDER BY số_flag DESC, chênh_tb_pct DESC
LIMIT 20;

-- Đánh dấu đã kiểm tra
UPDATE data_quality_flags
SET resolved = TRUE, resolved_at = NOW(),
    notes = 'Kiểm tra thủ công — VCI chính xác, KBS lệch do làm tròn'
WHERE symbol = 'HPG' AND period = '2023';
```

---

## 6. Tích hợp vào hệ thống hiện có

### 6.1 Không thay đổi gì ở Phase 1–6

Phase 7 hoàn toàn **additive** — thêm mới, không sửa code cũ:

| Thành phần cũ | Có bị sửa không |
|---|---|
| `sync_listing`, `sync_company`, `sync_ratios` | Không |
| `etl/extractors/listing/finance/company/trading.py` | Không |
| `etl/transformers/*` cũ | Không |
| Migrations 001–004 | Không |
| `etl/loaders/postgres.py` | Không — dùng nguyên vẹn |

`sync_financials.py` chỉ thêm 7–10 dòng gọi validator ở cuối — không đụng logic chính.

### 6.2 Toàn bộ file cần tạo mới

```
Phase 7A:
  etl/extractors/dnse_price.py        (primary — DNSE qua vnstock)
  etl/extractors/vndirect_price.py    (fallback — HTTP thủ công)
  etl/transformers/dnse_price.py
  etl/transformers/vndirect_price.py
  jobs/sync_prices.py
  db/migrations/005_price_history.sql

Phase 7B:
  etl/validators/__init__.py       (file rỗng)
  etl/validators/cross_source.py
  db/migrations/006_data_quality.sql
```

### 6.3 File hiện có cần sửa (chỉ thêm, không xóa)

```
config/constants.py     ← +JOB_SYNC_PRICES, +CONFLICT_KEYS entry
config/settings.py      ← +cron_sync_prices, +dnse_username, +dnse_password
scheduler/jobs.py       ← +sync_prices job
main.py                 ← +sync_prices subcommand
.env.example            ← +CRON_SYNC_PRICES, +DNSE_USERNAME, +DNSE_PASSWORD
jobs/sync_financials.py ← +gọi validator sau load (Phase 7B)
```

---

## 7. Rủi ro và giảm thiểu

### 7.1 Rủi ro chính

| Rủi ro | Mức độ | Biện pháp |
|---|---|---|
| **DNSE token hết hạn** (JWT 8h) | Thấp | vnstock tự refresh; nếu lỗi → fallback VNDirect tự động trong `_run_one()` |
| **DNSE đổi API hoặc policy** | Thấp–Trung bình | vnstock sẽ update; fallback VNDirect public không bị ảnh hưởng |
| **VNDirect khóa finfo-api** (undocumented) | Trung bình | `source` column trong DB cho phép đổi nguồn mà không mất dữ liệu cũ; KBS là backup cuối |
| **DNSE không có `adClose`** | Thấp | `close_adj` = NULL cho source='dnse'. Nếu cần adjusted close: chạy bổ sung với VNDirect hoặc tính manual từ sự kiện cổ tức |
| **KBS trả về schema khác** khi vnstock update | Thấp | Validator bắt exception và bỏ qua — không làm hỏng sync chính |
| **Cross-validate sai** do BCTC theo VAS vs IFRS | Trung bình | Chỉ so sánh 3 cột tổng hợp lớn (total_assets, net_profit, ...) — ít nhạy cảm với phương pháp kế toán |

### 7.2 Kế hoạch dự phòng phân tầng

```
Tầng 1: DNSE qua vnstock    → Ưu tiên, feed từ sàn
Tầng 2: VNDirect finfo-api  → Fallback tự động trong sync_prices._run_one()
Tầng 3: KBS qua vnstock     → Manual fallback cuối nếu cả 2 trên cùng sập
```

Để kích hoạt tầng 3 khi cần:
```python
# Không implement ngay — chỉ document để dùng khẩn cấp
from vnstock import Quote
df = Quote(symbol='HPG', source='KBS').history(start='2024-01-01', end='2024-12-31', interval='1D')
```

### 7.3 Tại sao không dùng thêm nguồn trả phí?

| Nguồn | Trạng thái | Ghi chú |
|---|---|---|
| **DNSE** | ✅ Đang dùng | Người dùng đã có tài khoản |
| **SSI FastConnect** | Tùy chọn nâng cấp | API program chính thức, SLA đảm bảo — phù hợp nếu lên production |
| **FireAnt** | Không ưu tiên | 5.4 triệu VND/năm |
| **FiinGroup** | Không ưu tiên | Enterprise pricing — gold standard nhưng chi phí cao |

> **Nâng cấp sau này:** Nếu DNSE không đủ hoặc cần SLA đảm bảo cho production, SSI FastConnect là lựa chọn tự nhiên tiếp theo.

---

## 8. Thứ tự implement

```
── PHASE 7A ────────────────────────────────────────────────────────

Bước 1  Tạo 005_price_history.sql → chạy: python -m db.migrate

Bước 2  Kiểm tra DNSE credentials với vnstock:
        python -c "
        from vnstock import Quote
        df = Quote(symbol='HPG', source='DNSE').history(
            start='2024-01-02', end='2024-01-05', interval='1D')
        print(df); print(df.dtypes)
        # Kiểm tra: giá HPG ngày 2024-01-02 có đúng ~27,000-28,000 VND không?
        # Nếu ~27.5 → vnstock DNSE trả về nghìn VND → set _NEEDS_SCALE = True"

Bước 3  Viết etl/extractors/dnse_price.py → test:
        python -c "
        from etl.extractors.dnse_price import DNSEPriceExtractor
        from datetime import date
        df = DNSEPriceExtractor().extract_price_history(
            'HPG', start=date(2024,1,1), end=date(2024,3,31))
        print(df.head()); print(df.dtypes)"

Bước 4  Viết etl/transformers/dnse_price.py → test:
        python -c "
        from etl.transformers.dnse_price import DNSEPriceTransformer
        # (dùng df từ bước 3)
        df2 = DNSEPriceTransformer().transform(df, 'HPG')
        print(df2.head()); print(df2.dtypes)
        # Kiểm tra: close của HPG 2024-01-02 phải là integer ~27000-28000"

Bước 5  Viết etl/extractors/vndirect_price.py + etl/transformers/vndirect_price.py
        (fallback — tương tự DNSE nhưng HTTP thủ công, có adClose)

Bước 6  Viết jobs/sync_prices.py

Bước 7  Cập nhật constants.py, settings.py, scheduler/jobs.py, main.py, .env.example

Bước 8  Test end-to-end (3 mã):
        python main.py sync_prices --symbol HPG VCB FPT --full-history
        → Kiểm tra:
          SELECT symbol, source, MIN(date), MAX(date), COUNT(*)
          FROM price_history GROUP BY symbol, source;

Bước 9  Test fallback: tạm thời raise Exception trong DNSEPriceExtractor.extract()
        để xác nhận VNDirect fallback được kích hoạt tự động.

Bước 10 Initial load toàn bộ (~1 giờ):
        python main.py sync_prices --full-history

── PHASE 7B ────────────────────────────────────────────────────────

Bước 11 Tạo 006_data_quality.sql → python -m db.migrate
Bước 12 Tạo etl/validators/__init__.py (file rỗng)
Bước 13 Viết cross_source.py → test thủ công:
        python -c "
        from etl.validators.cross_source import FinanceCrossValidator
        n = FinanceCrossValidator().validate_symbol('HPG')
        print(f'Flags: {n}')"
Bước 14 Tích hợp validator vào sync_financials.py
Bước 15 Test end-to-end:
        python main.py sync_financials --symbol HPG VCB
        → Kiểm tra: SELECT * FROM data_quality_flags LIMIT 20;
```

### Ước tính thời gian

| Giai đoạn | Công việc | Thời gian ước tính |
|---|---|---|
| 7A implement | Viết code + test DNSE + VNDirect fallback | 1–2 ngày |
| 7A initial load | `sync_prices --full-history` (~1,550 mã) | 45–90 phút |
| 7B implement | Viết code + test | 1 ngày |
| 7B first run | Chạy kèm `sync_financials` | +20–30% thời gian sync_financials |

---

*Tài liệu Phase 7 — cập nhật 2026-03-21: TCBS removed, VNDirect fallback, DNSE (người dùng có account) làm primary.*
*Xác nhận trước khi bắt đầu implement từng bước.*
