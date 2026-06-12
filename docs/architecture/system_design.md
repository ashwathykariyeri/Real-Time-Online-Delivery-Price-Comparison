# System Architecture — Real-Time Indian Grocery Price Comparison

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                      LIVE DATA SOURCES                               │
│  Blinkit │ Zepto │ Instamart │ BigBasket │ Amazon Fresh │ JioMart   │
│                         │ Dunzo                                      │
└─────────────────────────┬───────────────────────────────────────────┘
                          │  Playwright / Requests / API Intercept
                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│              INGESTION LAYER  (src/ingestion/)                       │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  scraper_manager.py                                            │  │
│  │  ThreadPoolExecutor(max_workers=7) — all platforms parallel    │  │
│  │  BlinkitScraper | ZeptoScraper | InstamartScraper | ...        │  │
│  └───────────────────────────────────────────────────────────────┘  │
│  Output JSON: { platform, product_name, price_inr, discount_pct,    │
│                 delivery_time_mins, quantity, unit, in_stock, ... }  │
└─────────────────────────┬───────────────────────────────────────────┘
                          │  kafka_producer.py  (kafka-python)
                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│              MESSAGE BROKER  (Apache Kafka)                          │
│  Topics:                                                             │
│    raw-prices     ← scraper output  (3 partitions)                  │
│    clean-prices   ← Spark output    (3 partitions)                  │
│    ml-scores      ← ML API output   (1 partition)                   │
│    search-events  ← user searches   (1 partition)                   │
└──────────┬──────────────────────────┬───────────────────────────────┘
           │ Kafka Connect JDBC Sink   │ Spark reads stream
           ▼                          ▼
┌─────────────────┐       ┌────────────────────────────────────────────┐
│  RAW STORE      │       │  STREAM PROCESSING  (Apache Spark 3.5)     │
│  MySQL 8.0      │       │  src/processing/spark_processor.py          │
│  raw_prices     │       │  ┌──────────────────────────────────────┐  │
└─────────────────┘       │  │  Every 10s (micro-batch):             │  │
                          │  │  1. Parse JSON from Kafka             │  │
                          │  │  2. Normalise units (g/mL/pcs)        │  │
                          │  │  3. Deduplicate (5-min watermark)      │  │
                          │  │  4. Calculate: discount%, savings,     │  │
                          │  │     price_rank across platforms        │  │
                          │  │  5. Flag out-of-stock items            │  │
                          │  │  6. Write to clean_store MySQL         │  │
                          │  └──────────────────────────────────────┘  │
                          └──────────────────┬─────────────────────────┘
                                             │ JDBC write
                                             ▼
                          ┌──────────────────────────────────────────┐
                          │  CLEAN STORE  (MySQL 8.0)                 │
                          │  Tables:                                  │
                          │    clean_prices   — processed listings    │
                          │    price_history  — daily snapshots       │
                          │    platforms      — platform metadata     │
                          │    search_history — analytics             │
                          │    price_alerts   — user alerts           │
                          │    deal_scores    — ML model output       │
                          └──────────────────┬───────────────────────┘
                                             │
                          ┌──────────────────┴───────────────────────┐
                          │  ML LAYER  (src/processing/)              │
                          │  ┌────────────────────────────────────┐  │
                          │  │  ml_model.py                        │  │
                          │  │  1. DealScorer (GradientBoosting)   │  │
                          │  │     Input: price, discount, delivery │  │
                          │  │     Output: 0–100 deal score         │  │
                          │  │  2. AnomalyDetector (IsolationForest)│  │
                          │  │     Flags unusual prices              │  │
                          │  │  3. TrendPredictor (LogisticRegress) │  │
                          │  │     Will price drop tomorrow?         │  │
                          │  └────────────────────────────────────┘  │
                          │  ml_api.py  — FastAPI REST server         │
                          │    POST /score    → deal scores           │
                          │    POST /anomaly  → anomaly flags         │
                          │    POST /trend    → price trend           │
                          │  MLflow server   — experiment tracking    │
                          └──────────────────┬───────────────────────┘
                                             │
                          ┌──────────────────▼───────────────────────┐
                          │  STREAMLIT DASHBOARD  (src/frontend/)     │
                          │  app.py          — search + card grid     │
                          │  pages/1_Compare — side-by-side table     │
                          │  pages/2_Trends  — 7/30-day price charts  │
                          │  pages/3_Deals   — best deals by score    │
                          │  pages/4_Alerts  — price alert system     │
                          │                                           │
                          │  URL: http://localhost:8501               │
                          └──────────────────────────────────────────┘
```

## Component Details

### Ingestion Layer

| Component | Technology | Purpose |
|-----------|-----------|---------|
| `blinkit_scraper.py` | Playwright + stealth | React SPA, pincode-gated |
| `zepto_scraper.py` | Playwright + webkit + stealth | Aggressive bot detection |
| `instamart_scraper.py` | requests (API intercept) | GraphQL/REST API |
| `bigbasket_scraper.py` | requests (API) | REST search API |
| `amazon_fresh_scraper.py` | requests + BeautifulSoup | HTML parsing |
| `jiomart_scraper.py` | requests (API) | REST catalog API |
| `dunzo_scraper.py` | requests (API + auth) | Auth-required REST API |
| `scraper_manager.py` | `concurrent.futures` | Parallel execution |
| `kafka_producer.py` | kafka-python | Topic: `raw-prices` |

### Anti-Bot Strategy

| Platform | Detection | Bypass |
|----------|-----------|--------|
| Blinkit | Location gate | Playwright sets pincode first |
| Zepto | `navigator.webdriver` | playwright-stealth + WebKit |
| Instamart | Session token | Cookie persistence |
| BigBasket | Pincode header | `bb_pincode` cookie |
| Amazon | IP rate limit | Rotating user agents |
| JioMart | Minimal | Standard headers |
| Dunzo | Bearer token | Token extraction from DevTools |

### Data Schema (key fields)

```json
{
  "platform": "Blinkit",
  "product_name": "Amul Full Cream Milk",
  "brand": "Amul",
  "price_inr": 66.0,
  "original_price_inr": 72.0,
  "discount_pct": 8.3,
  "quantity": "1",
  "unit": "L",
  "unit_label": "1 L",
  "price_per_unit": 6.6,
  "unit_norm": "per 100g",
  "delivery_time_mins": 9,
  "in_stock": true,
  "pincode": "110001",
  "deal_score": 74.5,
  "is_anomaly": false,
  "timestamp": "2024-03-15T10:30:00"
}
```

### Unit Normalisation Rules

| Input | Normalised | Display |
|-------|-----------|---------|
| `500g` | 500g | ₹X per 100g |
| `1 kg` | 1000g | ₹X per 100g |
| `500 mL` | 500mL | ₹X per 100mL |
| `1 L` | 1000mL | ₹X per 100mL |
| `6 pcs` | 6 pcs | ₹X per pc |
| `half kg` | 500g | ₹X per 100g |
| `1/2 liter` | 500mL | ₹X per 100mL |
| `2 x 500g` | 1000g | ₹X per 100g |
| `1 dozen` | 12 pcs | ₹X per pc |

### Service Ports

| Service | Port | URL |
|---------|------|-----|
| Streamlit Dashboard | 8501 | http://localhost:8501 |
| ML API (FastAPI) | 8000 | http://localhost:8000/docs |
| MLflow UI | 5001 | http://localhost:5001 |
| Kafka | 9092 | localhost:9092 |
| Zookeeper | 2181 | localhost:2181 |
| Schema Registry | 8081 | http://localhost:8081 |
| MySQL | 3306 | localhost:3306 |
| Spark Master UI | 8080 | http://localhost:8080 |
| Spark Worker UI | 8082 | http://localhost:8082 |
