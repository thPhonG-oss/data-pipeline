# DNSE MDDS System — Giải thích kỹ thuật (Tiếng Việt)

> Tài liệu này giải thích `DNSE - MDDS System - KRX v1.4.xlsx` và code mẫu `docs/MQTT/mqtt.py`.
> Cập nhật: 2026-03-21

---

## 1. MDDS là gì?

**MDDS = Market Data Distribution System** — Hệ thống phân phối dữ liệu thị trường của DNSE.

DNSE kết nối trực tiếp với **KRX** (Korea Exchange — hệ thống giao dịch hiện tại của HoSE và HNX từ 2022) để nhận dữ liệu thị trường nguyên gốc từ sàn theo thời gian thực, rồi phân phối lại cho khách hàng có tài khoản DNSE qua giao thức **MQTT over WebSocket** (WSS).

**Điểm quan trọng:** Đây là dữ liệu **real-time streaming**, không phải REST pull. Khác hoàn toàn với `Quote(source='DNSE').history()` — cái đó là REST historical batch.

---

## 2. Cơ chế kết nối

### Giao thức

| Thành phần | Giá trị |
|---|---|
| Giao thức | **MQTT v5** over **WebSocket Secure (WSS)** |
| Broker host | `datafeed-lts-krx.dnse.com.vn` |
| Broker port | `443` (HTTPS port — pass qua firewall) |
| WS path | `/wss` |
| SSL | Bật (self-signed cert, nên `CERT_NONE`) |

### Authentication — 2 bước

**Bước 1 — Lấy JWT token:**
```
POST https://api.dnse.com.vn/user-service/api/auth
Body: { "username": "<email/sdt>", "password": "<password>" }
→ Response: { "token": "<JWT>" }
```

**Bước 2 — Lấy InvestorID:**
```
GET https://api.dnse.com.vn/user-service/api/me
Header: Authorization: Bearer <token>
→ Response: { "investorId": 123456, ... }
```

**Bước 3 — Kết nối MQTT:**
- Username MQTT = `investorId` (số)
- Password MQTT = JWT token
- Client ID = chuỗi ngẫu nhiên, ví dụ `dnse-price-json-mqtt-ws-sub-1234`

```python
client.username_pw_set(investor_id, token)  # investorId, JWT
```

---

## 3. Các loại dữ liệu và topic

Sau khi kết nối, bạn **subscribe** vào các topic để nhận dữ liệu. Cấu trúc topic:

```
plaintext/quotes/krx/mdds/<type>/v1/<scope>/<param>
```

### 3.1 Stock Info (SI) — Thông tin tổng hợp mã

**Topic:** `plaintext/quotes/krx/mdds/stockinfo/v1/roundlot/symbol/{symbol}`

**Dùng để:** Nhận giá trần/sàn/tham chiếu, giá khớp, khối lượng, dữ liệu nước ngoài, trạng thái giao dịch của một mã.

**Fields quan trọng:**

| Field | Kiểu | Ý nghĩa |
|---|---|---|
| `referencePrice` | double | Giá tham chiếu |
| `highLimitPrice` | double | Giá trần |
| `lowLimitPrice` | double | Giá sàn |
| `matchPrice` | double | Giá khớp hiện tại |
| `matchQuantity` | uint64 | Khối lượng khớp gần nhất |
| `openPrice` | double | Giá mở cửa |
| `closePrice` | double | Giá đóng cửa |
| `totalVolumeTraded` | uint64 | Tổng KL giao dịch trong ngày |
| `grossTradeAmount` | double | Tổng giá trị giao dịch |
| `buyForeignQuantity` | uint64 | KL nước ngoài mua |
| `sellForeignQuantity` | uint64 | KL nước ngoài bán |
| `foreignerOrderLimitQuantity` | int | Room nước ngoài còn lại |
| `securityStatus` | int | Trạng thái giao dịch (Halt/Normal) |
| `tradingSessionId` | int | Phiên giao dịch (ATO/ATC/CONTINUOUS/...) |
| `boardId` | int | Bảng giao dịch (G1=lô chẵn, G4=lô lẻ, T1=thỏa thuận...) |

> **Lưu ý:** SI tách board "Sau giờ" (Post Closing = G3) ra topic riêng do trần/sàn thay đổi.

---

### 3.2 Top Price (TP) — Sổ lệnh Bid/Ask

**Topic:** `plaintext/quotes/krx/mdds/topprice/v1/roundlot/symbol/{symbol}`

**Dùng để:** Nhận 3 mức giá mua/bán tốt nhất (bid/offer). Giúp xây dựng order book.

**Fields quan trọng:**

| Field | Kiểu | Ý nghĩa |
|---|---|---|
| `bid` | object | `{ price: double, qtty: double }` — giá mua |
| `offer` | object | `{ price: double, qtty: double }` — giá bán |
| `buyTotalOrderQuantity` | double | Tổng KL dư mua |
| `sellTotalOrderQuantity` | double | Tổng KL dư bán |
| `symbol` | string | Mã chứng khoán |
| `sendingTime` | timestamp | Thời gian gửi |

---

### 3.3 Tick — Khớp lệnh từng giao dịch

**Topic:** `plaintext/quotes/krx/mdds/tick/v1/roundlot/symbol/{symbol}`

**Dùng để:** Nhận từng lệnh khớp (trade tick) theo thời gian thực. Đây là data granular nhất.

**Fields quan trọng:**

| Field | Kiểu | Ý nghĩa |
|---|---|---|
| `matchPrice` | double | Giá khớp |
| `matchQtty` | double | Khối lượng khớp |
| `side` | int | 1=Mua chủ động, 2=Bán chủ động |
| `totalVolumeTraded` | uint64 | Tổng KL lũy kế trong ngày |
| `grossTradeAmount` | double | Tổng giá trị lũy kế |
| `sendingTime` | timestamp | Thời điểm khớp |
| `tradingSessionId` | int | Phiên (ATO/Continuous/ATC...) |

> **Đây là data trong code mẫu `mqtt.py`** — subscribe topic Tick để nhận real-time trades.

---

### 3.4 Board Event (BE) — Sự kiện phiên giao dịch

**Topic:** `plaintext/quotes/krx/mdds/boardevent/v1/roundlot/market/{marketId}/product/{tscProductGrpId}`

**Dùng để:** Theo dõi trạng thái phiên: mở phiên, đóng phiên, chuyển giữa ATO → Continuous → ATC.

**marketId + productId mẫu:**
- `STO/STO` = HoSE cổ phiếu, ETF, CW, CCQ
- `BDO/BDO` = HoSE trái phiếu
- `STX/STX` = HNX cổ phiếu
- `UPX/UPX` = UpCOM
- `DVX/FIO` = Phái sinh Index Future
- `DVX/FBX` = Phái sinh Bond Future

---

### 3.5 Market Index — Chỉ số thị trường

**Topic:** `plaintext/quotes/krx/mdds/index/{indexName}`

**indexName hỗ trợ:** `VNINDEX`, `VN30`, `HNX`, `HNX30`, `UPCOM`, `VNXAllShare`

**Fields quan trọng:**

| Field | Kiểu | Ý nghĩa |
|---|---|---|
| `valueIndexes` | double | Giá trị chỉ số hiện tại |
| `changedValue` | double | Thay đổi điểm |
| `changedRatio` | double | % thay đổi |
| `priorValueIndexes` | double | Giá trị tham chiếu |
| `totalVolumeTraded` | uint64 | Tổng KL toàn thị trường |
| `grossTradeAmount` | double | Tổng giá trị toàn thị trường |
| `fluctuationUpperLimitIssueCount` | uint32 | Số mã giá trần |
| `fluctuationUpIssueCount` | uint32 | Số mã tăng |
| `fluctuationSteadinessIssueCount` | uint32 | Số mã đứng giá |
| `fluctuationDownIssueCount` | uint32 | Số mã giảm |
| `fluctuationLowerLimitIssueCount` | uint32 | Số mã giá sàn |

---

### 3.6 OHLC — Dữ liệu nến real-time

**Đây là điểm quan trọng nhất cho pipeline!**

| Interface | Topic | Dùng cho |
|---|---|---|
| OHLC Stock | `plaintext/quotes/krx/mdds/v2/ohlc/stock/{resolution}/{symbol}` | Nến cổ phiếu |
| OHLC Index | `plaintext/quotes/krx/mdds/v2/ohlc/index/{resolution}/{indexName}` | Nến chỉ số |
| OHLC Derivative | `plaintext/quotes/krx/mdds/v2/ohlc/derivative/{resolution}/{symbol}` | Nến phái sinh |

**Resolution (timeframe) hỗ trợ:** `1`, `3`, `5`, `15`, `30`, `1H`, `1D`

**Fields:**

| Field | Kiểu | Ý nghĩa |
|---|---|---|
| `time` | timestamp | Thời gian nến |
| `open` | double | Giá mở cửa nến |
| `high` | double | Giá cao nhất nến |
| `low` | double | Giá thấp nhất nến |
| `close` | double | Giá đóng cửa nến |
| `volume` | uint64 | Khối lượng trong nến |
| `symbol` | string | Mã |
| `resolution` | string | Timeframe (`1D`, `1H`, `5`...) |
| `type` | string | `STOCK` / `INDEX` / `DERIVATIVE` |
| `lastUpdated` | timestamp | Cập nhật lần cuối |

**Ví dụ subscribe nến 1 ngày của HPG:**
```python
client.subscribe("plaintext/quotes/krx/mdds/v2/ohlc/stock/1D/HPG", qos=1)
```

---

## 4. Phân tích code mẫu `docs/MQTT/mqtt.py`

Code mẫu thực hiện đúng luồng: auth → lấy investorId → kết nối MQTT → subscribe Tick.

**Điểm cần lưu ý khi dùng trong production:**

| Vấn đề | Giải pháp đề xuất |
|---|---|
| JWT token hết hạn (8h) | Bắt disconnect event, re-auth và reconnect |
| SSL self-signed | `tls_insecure_set(True)` — chấp nhận được cho internal feed |
| Client ID phải unique | Dùng `uuid4()` thay `randint` để tránh conflict |
| `while True: pass` tốn CPU | Dùng `loop_forever()` thay `loop_start() + while True` |
| Topic cứng (41I1F7000) | Thay bằng symbol chuẩn (HPG, VCB...) |
| Không reconnect | Thêm `client.on_disconnect` callback |

---

## 5. Vị trí MDDS trong pipeline hiện tại

```
Pipeline hiện tại (Phase 1-6)          MDDS có thể phục vụ
─────────────────────────────          ──────────────────────────────────
REST Historical (batch, daily):        Real-time streaming (tick/OHLC):
  Quote(source='DNSE').history()   ←→  subscribe ohlc/1D → lấy nến ngay
  → Phase 7A (sync_prices job)         → Tương lai: live price feed

Batch sync lúc 19:00:                  Intraday (nếu cần):
  Chạy sau đóng cửa mỗi ngày          subscribe ohlc/1 → tick-by-tick
  → Đơn giản, phù hợp Phase 7A        → Phức tạp hơn, cần message queue
```

**Kết luận cho Phase 7:**
- **Phase 7A** dùng **REST historical** (`Quote(source='DNSE').history()`) — không dùng MQTT. Đơn giản, không cần giữ kết nối persistent, phù hợp batch job.
- **MQTT/MDDS** là tài liệu tham khảo cho **tương lai** nếu cần real-time tick data hoặc intraday OHLC streaming.

---

## 6. Bảng tổng hợp — Interface và Use Case

| Interface | Topic pattern | Use case | Khi nào dùng |
|---|---|---|---|
| **Tick** | `.../tick/v1/roundlot/symbol/{sym}` | Mỗi lệnh khớp | Phân tích flow, real-time alert |
| **Stock Info** | `.../stockinfo/v1/roundlot/symbol/{sym}` | Tổng hợp mã | Dashboard, breadth analysis |
| **Top Price** | `.../topprice/v1/roundlot/symbol/{sym}` | Sổ lệnh bid/ask | Market depth, spread analysis |
| **OHLC Stock** | `.../v2/ohlc/stock/{res}/{sym}` | Nến real-time | Intraday chart, kỹ thuật |
| **Board Event** | `.../boardevent/v1/roundlot/market/...` | Trạng thái phiên | Biết lúc nào ATO/ATC/đóng cửa |
| **Market Index** | `.../index/{indexName}` | Chỉ số tổng hợp | Breadth, thị trường toàn cảnh |

---

## 7. Các sàn và board giao dịch

### MarketID

| ID | Sàn | Ý nghĩa |
|---|---|---|
| STO | HoSE | Cổ phiếu HoSE |
| BDO | HoSE | Trái phiếu HoSE |
| STX | HNX | Cổ phiếu HNX niêm yết |
| UPX | HNX | UpCOM |
| DVX | HNX | Phái sinh |
| BDX | HNX | Trái phiếu chính phủ |
| HCX | HNX | Trái phiếu doanh nghiệp HNX |

### BoardID (bảng giao dịch)

| Board | Loại |
|---|---|
| G1 | Lô chẵn trong giờ (DNSE gộp G1+G7) |
| G3 | Lô chẵn Post Closing (sau giờ) |
| G4 | Lô lẻ |
| T1 | Thỏa thuận lô chẵn trong giờ (DNSE gộp T1+T2) |
| T3 | Thỏa thuận lô chẵn sau giờ |
| T4 | Thỏa thuận lô lẻ trong giờ |

### TradingSessionID (phiên giao dịch)

| ID | Tên | Ý nghĩa |
|---|---|---|
| 10 | Opening Call Auction | ATO — Khớp lệnh định kỳ mở cửa |
| 30 | Closing Call Auction | ATC — Khớp lệnh định kỳ đóng cửa |
| 40 | Continuous Auction | CONTINUOUS — Khớp lệnh liên tục |
| 90 | Trading Halt | Tạm dừng giao dịch |
| 99 | Board Closing | Đóng bảng (end of day) |

---

## 8. Tóm tắt

DNSE MDDS là hệ thống data feed **real-time chất lượng cao**, nhận dữ liệu thẳng từ KRX (sàn giao dịch). Điểm mạnh:

- **Latency cực thấp**: Feed trực tiếp từ sàn, không qua aggregator trung gian
- **Đầy đủ data types**: Tick, OHLC, Order book, Index, Session events
- **Nhiều timeframe**: 1m, 3m, 5m, 15m, 30m, 1H, 1D
- **Phái sinh và chỉ số**: Không chỉ cổ phiếu

Điểm hạn chế cho pipeline hiện tại:

- **Cần tài khoản DNSE** (đã có)
- **JWT hết hạn sau 8h** → cần auto-refresh khi chạy 24/7
- **Persistent connection** → phức tạp hơn REST batch
- **Chỉ real-time** → không thay thế được REST historical cho backfill

**Với Phase 7A, dùng REST historical (`Quote(source='DNSE').history()`) là đúng quyết định.** MQTT/MDDS là nền tảng cho tương lai nếu muốn xây real-time pipeline.
