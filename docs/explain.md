# Giải thích các thư viện vnstock trong dự án Data Pipeline

## Tổng quan

Dự án sử dụng 4 thư viện chính thuộc hệ sinh thái **vnstock** để xây dựng pipeline dữ liệu chứng khoán Việt Nam:

| Thư viện | Phiên bản | Mục đích |
|---|---|---|
| `vnstock_data` | 3.0.0 | Lấy dữ liệu tài chính từ nhiều nguồn |
| `vnstock_news` | 2.1.4 | Thu thập và phân tích tin tức tài chính |
| `vnstock_pipeline` | 2.2.1 | Xây dựng ETL pipeline tự động |
| `vnstock_ta` | 0.1.2 | Phân tích kỹ thuật và vẽ biểu đồ |

Tất cả đều phụ thuộc vào thư viện nền tảng `vnstock` và đều làm việc chủ yếu với dữ liệu dạng `pandas.DataFrame`.

---

## 1. vnstock_data — Lấy dữ liệu tài chính

### Mục đích

`vnstock_data` là lớp trừu tượng (abstraction layer) giúp lấy dữ liệu thị trường chứng khoán Việt Nam từ nhiều nhà cung cấp khác nhau như **VCI, KBS, VND, MAS, CAFEF, SPL**. Thay vì viết code riêng cho từng nguồn, bạn chỉ cần đổi tham số `source` là được.

### Kiến trúc

Thư viện dùng **Provider Registry Pattern**: mỗi nguồn dữ liệu được đăng ký vào một registry trung tâm. Lớp `BaseAdapter` xử lý việc chọn đúng provider, tự lọc tham số phù hợp, và thực hiện retry tự động khi gặp lỗi.

### Các lớp API chính

#### `Quote` — Dữ liệu giá cổ phiếu

```python
from vnstock_data import Quote

q = Quote(source="vci", symbol="HPG")

# Lấy lịch sử giá theo ngày
df = q.history(start="2024-01-01", end="2024-12-31", interval="1D")

# Lấy dữ liệu trong ngày (intraday)
df_intraday = q.intraday(page_size=100)

# Lấy độ sâu thị trường (order book)
df_depth = q.price_depth()
```

- **Nguồn hỗ trợ**: VCI, KBS, VND, MAS
- **interval**: `"1D"` (ngày), `"1W"` (tuần), `"1M"` (tháng), `"1"` (1 phút), `"5"`, `"15"`, `"30"`, `"60"`

#### `Finance` — Báo cáo tài chính

```python
from vnstock_data import Finance

# Lấy báo cáo theo năm
fin = Finance(source="vci", symbol="HPG", period="year")

df_bs  = fin.balance_sheet(lang="vi")      # Bảng cân đối kế toán
df_is  = fin.income_statement(lang="vi")   # Báo cáo kết quả kinh doanh
df_cf  = fin.cash_flow(lang="vi")          # Báo cáo lưu chuyển tiền tệ
df_rat = fin.ratio(lang="vi")              # Các chỉ số tài chính
df_note = fin.note(lang="vi")             # Thuyết minh (chỉ VCI)

# Lấy báo cáo theo quý
fin_q = Finance(source="vci", symbol="HPG", period="quarter")
df_cf_q = fin_q.cash_flow(lang="vi")
```

- **period**: `"year"` hoặc `"quarter"`
- **lang**: `"vi"` (tiếng Việt) hoặc `"en"` (tiếng Anh)
- **Nguồn hỗ trợ**: VCI, MAS, KBS

#### `Listing` — Danh sách chứng khoán

```python
from vnstock_data import Listing

lst = Listing(source="vci")

# Toàn bộ mã chứng khoán đang niêm yết
df_all = lst.all_symbols()

# Phân loại theo ngành ICB
df_industry = lst.symbols_by_industries()

# Phân loại theo sàn giao dịch
df_exchange = lst.symbols_by_exchange()

# Nhóm cổ phiếu: VN30, HNX30, MIDCAP, SMALLCAP, CW, BOND, ETF...
df_vn30 = lst.symbols_by_group(group="VN30")

# Danh sách tất cả các chỉ số thị trường
df_indices = lst.all_indices()

# ETF, trái phiếu, chứng quyền
df_etf   = lst.all_etf()
df_bonds = lst.all_bonds()
df_cw    = lst.all_covered_warrant()
```

#### `Trading` — Dữ liệu giao dịch

```python
from vnstock_data import Trading

tr = Trading(source="vci", symbol="HPG")

# Thống kê giao dịch
df_stats = tr.trading_stats(start="2024-01-01", end="2024-12-31")

# Bảng giá nhiều mã cùng lúc
df_board = tr.price_board(symbols_list=["HPG", "VCB", "VNM"])

# Giao dịch khối ngoại
df_foreign = tr.foreign_trade()

# Giao dịch tự doanh
df_prop = tr.prop_trade()

# Giao dịch của nội bộ
df_insider = tr.insider_deal()
```

#### `TopStock` — Thống kê thị trường (nguồn VND)

```python
from vnstock_data import TopStock

top = TopStock(source="vnd")

# Top tăng/giảm mạnh nhất
df_gainers = top.gainer(index="VNINDEX", limit=10)
df_losers  = top.loser(index="VNINDEX", limit=10)

# Top theo thanh khoản
df_value  = top.value(index="VNINDEX", limit=10)
df_volume = top.volume(index="VNINDEX", limit=10)

# Top mua/bán ròng khối ngoại
df_fbuy  = top.foreign_buy(date="2024-06-10", limit=10)
df_fsell = top.foreign_sell(date="2024-06-10", limit=10)
```

#### `CommodityPrice` — Giá hàng hóa

```python
from vnstock_data import CommodityPrice

com = CommodityPrice(source="spl")

df_gold_vn     = com.gold_vn()        # Giá vàng trong nước
df_gold_global = com.gold_global()    # Giá vàng thế giới
df_gas         = com.gas_vn()         # Giá xăng dầu
df_steel       = com.steel_d10()      # Giá thép
df_oil         = com.oil_crude()      # Giá dầu thô
```

---

## 2. vnstock_news — Thu thập tin tức tài chính

### Mục đích

`vnstock_news` thu thập, lọc, và phân tích tin tức tài chính Việt Nam từ nhiều nguồn (RSS feeds, sitemaps). Hỗ trợ xử lý bất đồng bộ (async), cache nhiều backend, làm sạch nội dung, và phân tích xu hướng (trending topics).

### Các lớp chính

#### `EnhancedNewsCrawler` — Crawler nâng cao

Đây là class chính, có đầy đủ tính năng nhất:

```python
from vnstock_news import EnhancedNewsCrawler

# Khởi tạo với cache
crawler = EnhancedNewsCrawler(
    cache_enabled=True,
    cache_ttl=3600,       # Cache 1 giờ (giây)
    max_concurrency=8     # Tối đa 8 request song song
)

# Lấy bài viết từ nhiều nguồn
df = crawler.fetch_articles(
    sources=["https://cafef.vn", "https://vneconomy.vn"],
    max_articles=200,
    time_frame="1d",      # Lọc bài trong 1 ngày gần nhất
    clean_content=True,   # Làm sạch nội dung HTML
    save_to_file="news.csv"
)

# Xem danh sách site được hỗ trợ
sites = crawler.get_SITES_CONFIG()
```

- **time_frame**: `"1d"` (1 ngày), `"6h"` (6 giờ), `"12h"`, `"7d"`...
- **sort_order**: `"newest"` hoặc `"oldest"`
- **cache backends**: `"memory"`, `"file"`, `"sqlite"`

#### `Crawler` — Crawler cơ bản

```python
from vnstock_news.core.crawler import Crawler

crawler = Crawler(site_name="cafef")

# Lấy bài viết từ RSS
articles = crawler.get_articles_from_feed(limit_per_feed=20)

# Lấy bài mới nhất từ sitemap
articles = crawler.get_latest_articles(limit=50)

# Lấy nội dung chi tiết 1 bài
detail = crawler.get_article_details("https://cafef.vn/...")
```

#### `BatchCrawler` — Crawl hàng loạt

```python
from vnstock_news.core.batch import BatchCrawler

batch = BatchCrawler(output_dir="./news_data")

# Crawl và lưu kết quả, hỗ trợ tiếp tục nếu bị ngắt
batch.fetch_articles(
    sitemap_url="https://cafef.vn/sitemap.xml",
    limit=500,
    within="24h"    # Chỉ lấy bài trong 24 giờ gần nhất
)
```

#### `TrendingAnalyzer` — Phân tích xu hướng

```python
from vnstock_news.trending.analyzer import TrendingAnalyzer

analyzer = TrendingAnalyzer()
trends = analyzer.analyze(df_articles)  # df từ crawler
# Trả về từ khóa/cụm từ xuất hiện nhiều nhất
```

### Scheduler tự động (main.py)

Module `vnstock_news.main` chạy như một service lên lịch tự động:
- Thu thập tin tức định kỳ mỗi N phút
- Cập nhật sitemap theo giờ/ngày
- Theo dõi trending topics
- Lưu vào CSV có archive và báo cáo JSON

---

## 3. vnstock_pipeline — ETL Pipeline tự động

### Mục đích

`vnstock_pipeline` là framework ETL (Extract → Transform → Load) giúp tự động hóa việc lấy, kiểm tra, chuyển đổi và lưu dữ liệu cho nhiều mã chứng khoán cùng lúc. Hỗ trợ xử lý song song, retry, và xuất ra nhiều định dạng (CSV, Parquet, DuckDB).

### Kiến trúc ETL

```
[Fetcher] → [Validator] → [Transformer] → [Exporter]
   Lấy dữ liệu   Kiểm tra    Biến đổi dữ liệu   Lưu xuống
```

Mỗi bước là một abstract class — bạn kế thừa và implement theo nhu cầu.

### Các lớp cốt lõi

#### `Scheduler` — Chạy pipeline cho nhiều mã

```python
from vnstock_pipeline.core.scheduler import Scheduler

scheduler = Scheduler(
    fetcher=my_fetcher,
    validator=my_validator,
    transformer=my_transformer,
    exporter=my_exporter,
    retry_attempts=3,
    max_workers=5       # Số luồng song song
)

scheduler.run(
    tickers=["HPG", "VCB", "VNM", "FPT"],
    fetcher_kwargs={"start": "2024-01-01", "end": "2024-12-31", "interval": "1D"},
    request_delay=0.5   # Nghỉ 0.5s giữa các request để tránh bị block
)
```

- Tự động dùng xử lý **song song** khi có hơn 10 mã
- In báo cáo tóm tắt: số thành công, thất bại, thời gian xử lý
- Lưu lỗi vào file CSV riêng

#### `TimeSeriesExporter` — Xuất dữ liệu chuỗi thời gian

```python
from vnstock_pipeline.core.exporter import TimeSeriesExporter

exporter = TimeSeriesExporter(
    base_path="./data",
    file_format="parquet",   # hoặc "csv"
    mode="append",           # hoặc "overwrite"
    dedup_columns=["time"]   # Cột dùng để loại trùng lặp
)
```

#### `DataManager` — Quản lý dữ liệu có tổ chức

```python
from vnstock_pipeline.core.data_manager import DataManager

dm = DataManager(base_path="./data")

# Lưu dữ liệu có phân vùng theo ngày
dm.save_data(df, ticker="HPG", data_type="ohlcv", date="2024-06-10")

# Load dữ liệu với bộ lọc
df = dm.load_data(
    ticker="HPG",
    data_type="ohlcv",
    start_date="2024-01-01",
    end_date="2024-06-30",
    columns=["time", "open", "high", "low", "close", "volume"]
)

# Cấu trúc thư mục tự động:
# ./data/ohlcv/2024-06-10/HPG.parquet
```

#### `BaseWebSocketClient` — Streaming dữ liệu thời gian thực

```python
from vnstock_pipeline.stream.client import BaseWebSocketClient

class MyStreamClient(BaseWebSocketClient):
    async def on_message(self, message):
        # Xử lý message thời gian thực
        pass

client = MyStreamClient(url="wss://...")
await client.connect()
await client.wait_until_disconnected()
```

### Template sẵn có (vnstock_pipeline.template)

Thư viện cung cấp template giúp tích hợp nhanh với `vnstock_data`:

```python
from vnstock_pipeline.template.vnstock import VNFetcher, VNValidator, VNTransformer
from vnstock_data import Quote

# Chỉ cần override _vn_call()
class OHLCVFetcher(VNFetcher):
    def _vn_call(self, ticker, **kwargs):
        return Quote(symbol=ticker, source="vci").history(**kwargs)

fetcher    = OHLCVFetcher()
validator  = VNValidator(required_columns=["time", "open", "high", "low", "close", "volume"])
transformer = VNTransformer()   # Tự chuyển cột 'time' sang datetime, sort, reset index
```

### Tasks có sẵn (vnstock_pipeline.tasks)

Thư viện có sẵn các task đã được xây dựng hoàn chỉnh:

```python
# Task lấy dữ liệu giá ngày (OHLCV)
from vnstock_pipeline.tasks.ohlcv import run_task

run_task(
    tickers=["HPG", "VCB"],
    start="2024-01-01",
    end="2024-12-31",
    interval="1D"
)

# Task lấy báo cáo tài chính
from vnstock_pipeline.tasks.financial import run_financial_task

run_financial_task(
    tickers=["HPG", "VCB"],
    lang="vi",
    dropna=True
)
# Tự động lưu ra các file: balance_sheet.csv, income_statement.csv, cash_flow.csv, ratio.csv
```

---

## 4. vnstock_ta — Phân tích kỹ thuật

### Mục đích

`vnstock_ta` cung cấp các chỉ báo phân tích kỹ thuật (Technical Analysis) và biểu đồ cho dữ liệu chứng khoán. Được xây dựng trên nền `pta_reload` (pandas-ta) và `pyecharts`.

### Sử dụng cơ bản

```python
from vnstock_ta import Indicator, Plotter
from vnstock_ta.get_data import DataSource

# Lấy dữ liệu
data_source = DataSource(
    symbol="HPG",
    start="2024-01-01",
    end="2024-12-31",
    interval="1D",
    source="vci"
)

# Khởi tạo bộ tính chỉ báo
ind = Indicator(data_source.data)
```

### Các nhóm chỉ báo

#### Trend — Xu hướng

```python
# Simple Moving Average (trung bình động đơn giản)
df_sma = ind.trend.sma(length=20)

# Exponential Moving Average (trung bình động hàm mũ)
df_ema = ind.trend.ema(length=20)

# Volume Weighted Average Price
df_vwap = ind.trend.vwap(anchor="D")

# Average Directional Index (sức mạnh xu hướng)
df_adx = ind.trend.adx(length=14)

# Aroon Indicator
df_aroon = ind.trend.aroon(length=14)

# Parabolic SAR
df_psar = ind.trend.psar(af0=0.02, af=0.02, max_af=0.2)

# Supertrend
df_st = ind.trend.supertrend(length=10, multiplier=3)
```

#### Momentum — Động lượng

```python
# Relative Strength Index (chỉ số sức mạnh tương đối)
df_rsi = ind.momentum.rsi(length=14)

# MACD (Moving Average Convergence Divergence)
df_macd = ind.momentum.macd(fast=12, slow=26, signal=9)

# Stochastic Oscillator
df_stoch = ind.momentum.stoch(k=14, d=3, smooth_k=3)

# Williams %R
df_willr = ind.momentum.willr(length=14)

# Rate of Change
df_roc = ind.momentum.roc(length=9)

# Momentum
df_mom = ind.momentum.mom(length=10)
```

#### Volatility — Biến động

```python
df_vol = ind.volatility.bbands(length=20, std=2)   # Bollinger Bands
```

#### Volume — Khối lượng

```python
# On-Balance Volume
df_obv = ind.volume.obv()
```

### Vẽ biểu đồ

```python
plotter = Plotter(data_source.data, theme="dark")   # hoặc "light"

# Vẽ SMA trên biểu đồ giá
plotter.trend.sma(length=20)

# Vẽ MACD
plotter.momentum.macd(fast=12, slow=26, signal=9)

# Vẽ RSI
plotter.momentum.rsi(length=14)
```

---

## 5. Luồng sử dụng tích hợp đầy đủ

Đây là ví dụ kết hợp cả 4 thư viện trong một pipeline hoàn chỉnh:

```python
# ── BƯỚC 1: Lấy danh sách mã cần phân tích ──────────────────────────
from vnstock_data import Listing, Finance

listing = Listing(source="vci")
vn30 = listing.symbols_by_group(group="VN30")
tickers = vn30["ticker"].tolist()

# ── BƯỚC 2: Chạy pipeline lấy dữ liệu giá & tài chính ────────────────
from vnstock_pipeline.tasks.ohlcv import run_task
from vnstock_pipeline.tasks.financial import run_financial_task

run_task(tickers, start="2023-01-01", end="2024-12-31", interval="1D")
run_financial_task(tickers, lang="vi")

# ── BƯỚC 3: Thu thập tin tức liên quan ───────────────────────────────
from vnstock_news import EnhancedNewsCrawler

crawler = EnhancedNewsCrawler(cache_enabled=True)
news = crawler.fetch_articles(
    sources=["https://cafef.vn", "https://vneconomy.vn"],
    max_articles=500,
    time_frame="7d"
)
news.to_csv("./data/news_7days.csv", index=False, encoding="utf-8-sig")

# ── BƯỚC 4: Phân tích kỹ thuật cho 1 mã cụ thể ───────────────────────
from vnstock_ta import Indicator
from vnstock_ta.get_data import DataSource

ds = DataSource(symbol="HPG", start="2024-01-01", end="2024-12-31")
ind = Indicator(ds.data)

df_result = ds.data.copy()
df_result["sma20"]   = ind.trend.sma(length=20)["SMA_20"]
df_result["ema50"]   = ind.trend.ema(length=50)["EMA_50"]
df_result["rsi14"]   = ind.momentum.rsi(length=14)["RSI_14"]
df_result["macd"]    = ind.momentum.macd()["MACD_12_26_9"]

df_result.to_csv("./data/HPG_analysis.csv", index=False, encoding="utf-8-sig")
```

---

## 6. Sơ đồ phụ thuộc

```
vnstock (thư viện nền tảng)
    ├── vnstock_data      ← Lấy dữ liệu thô từ nhiều nguồn
    │       ↑
    ├── vnstock_pipeline  ← Tự động hóa ETL, dùng vnstock_data để fetch
    │
    ├── vnstock_ta        ← Phân tích kỹ thuật, dùng dữ liệu từ vnstock/vnstock_data
    │
    └── vnstock_news      ← Độc lập, chuyên thu thập tin tức
```

---

## 7. Các tham số phổ biến cần nhớ

| Tham số | Giá trị | Dùng ở đâu |
|---|---|---|
| `source` | `"vci"`, `"kbs"`, `"vnd"`, `"mas"`, `"cafef"` | vnstock_data (tất cả class) |
| `period` | `"year"`, `"quarter"` | `Finance` |
| `lang` | `"vi"`, `"en"` | `Finance` |
| `interval` | `"1D"`, `"1W"`, `"1M"`, `"1"`, `"5"`, `"15"`, `"30"`, `"60"` | `Quote.history()` |
| `time_frame` | `"1d"`, `"6h"`, `"12h"`, `"7d"` | `EnhancedNewsCrawler` |
| `file_format` | `"csv"`, `"parquet"` | `TimeSeriesExporter` |
| `mode` | `"append"`, `"overwrite"` | `TimeSeriesExporter` |
