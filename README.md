# 🛒 Real-Time Indian Grocery Price Comparison

A complete **Data Engineering pipeline** that scrapes live grocery prices from India's top quick-commerce platforms in real time, streams them through **Apache Kafka**, processes with **Apache Spark**, stores in **SQLite**, and presents everything on an interactive **Streamlit** dashboard.

> ✅ **100% real-time data** — no cached datasets, no fake prices. Every search hits live websites via headless Chrome.

---

## 🏗️ Pipeline Architecture

```
User enters product + pincode
         │
         ▼
┌─────────────────────┐
│  PHASE 1: SCRAPING  │  Selenium headless Chrome — 4 platforms
│  Amazon Fresh       │  BeautifulSoup parses HTML / __NEXT_DATA__
│  Blinkit            │  localStorage/cookie injection for location
│  BigBasket          │
│  Zepto              │
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  PHASE 2: KAFKA     │  Real broker at localhost:9092 (KRaft mode)
│  Producer           │  Offset snapshot → no stale messages
│  Consumer           │  In-memory fallback if broker is down
│  Topic: raw-prices  │
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  PHASE 3: SPARK     │  Apache Spark 4.x  local[2]
│  ₹/unit normalise   │  value_score = price/unit × delivery penalty
│  Rank products      │  Pandas fallback if PySpark not installed
│  Flag best deal     │
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  PHASE 4: SQLITE    │  Built into Python — zero setup
│  searches table     │  Auto-created on first run
│  prices table       │
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  STREAMLIT UI       │  http://localhost:8501
│  Results table      │  Live terminal · Price chart
│  Buy links          │  Pipeline timings · Raw JSON
│  Search history     │
└─────────────────────┘
```

---

## 🖥️ Prerequisites — Both Platforms

| Requirement | Version | Download |
|-------------|---------|----------|
| **Python** | 3.10 or later | [python.org](https://python.org) |
| **Java (JDK)** | 11 or later | [adoptium.net](https://adoptium.net) |
| **Google Chrome** | Any recent | [google.com/chrome](https://google.com/chrome) |
| **Apache Kafka** | 3.9+ (optional) | [kafka.apache.org](https://kafka.apache.org/downloads) — app works without it |

---

## 🍎 Mac Setup Guide

### Step 1 — Install system dependencies

```bash
# Install Homebrew if you don't have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python 3.10+
brew install python@3.10

# Install Java 11+ (needed for Kafka and Spark)
brew install --cask temurin

# Verify Java
java -version
```

### Step 2 — Clone the repo

```bash
git clone https://github.com/adarsh-ue/Real-Time-Online-Delivery-Price-Comparison.git
cd Real-Time-Online-Delivery-Price-Comparison
```

### Step 3 — Install Python dependencies

```bash
pip3 install -r requirements.txt
```

### Step 4 — Install Apache Kafka (optional but recommended)

```bash
# Download Kafka 3.9.2
curl -L "https://downloads.apache.org/kafka/3.9.2/kafka_2.13-3.9.2.tgz" \
     -o ~/Downloads/kafka.tgz

# Extract to home folder
tar -xzf ~/Downloads/kafka.tgz -C ~/
mv ~/kafka_2.13-3.9.2 ~/kafka

# Format Kafka storage (KRaft mode — no ZooKeeper needed)
UUID=$(~/kafka/bin/kafka-storage.sh random-uuid)

# Edit log.dirs in the config (change /tmp/kraft-combined-logs to a real path)
sed -i '' 's|log.dirs=/tmp/kraft-combined-logs|log.dirs=/Users/'"$USER"'/kafka-logs|' \
    ~/kafka/config/kraft/server.properties

# Format storage
~/kafka/bin/kafka-storage.sh format \
    --config ~/kafka/config/kraft/server.properties \
    --cluster-id "$UUID"
```

> **Note:** No winutils needed on Mac. Spark runs natively.

### Step 5 — Run the app

**Option A — One-click launcher (recommended):**

```bash
chmod +x start_app.sh
./start_app.sh
```

This automatically starts Kafka, waits for the broker, then launches Streamlit at `http://localhost:8501`.

**Option B — Manual (two terminals):**

```bash
# Terminal 1 — Start Kafka
export KAFKA_HEAP_OPTS="-Xmx1G -Xms1G"
~/kafka/bin/kafka-server-start.sh ~/kafka/config/kraft/server.properties

# Terminal 2 — Start app
export PYTHONIOENCODING=utf-8
python3 -m streamlit run app.py
```

---

## 🪟 Windows Setup Guide

### Step 1 — Install system dependencies

1. Install **Python 3.10+** from [python.org](https://python.org)
   - ✅ Check **"Add Python to PATH"** during install

2. Install **Java 11+** from [adoptium.net](https://adoptium.net)
   - After install, set `JAVA_HOME` in System Environment Variables:
     ```
     Variable: JAVA_HOME
     Value:    C:\Program Files\Eclipse Adoptium\jdk-XX.X.X.XX-hotspot
     ```

3. Install **Google Chrome** from [google.com/chrome](https://google.com/chrome)

### Step 2 — Clone the repo

```powershell
git clone https://github.com/adarsh-ue/Real-Time-Online-Delivery-Price-Comparison.git
cd Real-Time-Online-Delivery-Price-Comparison
```

### Step 3 — Install Python dependencies

```powershell
pip install -r requirements.txt
```

### Step 4 — Install Apache Kafka (optional but recommended)

```powershell
# Download Kafka 3.9.2
Invoke-WebRequest `
  -Uri "https://downloads.apache.org/kafka/3.9.2/kafka_2.13-3.9.2.tgz" `
  -OutFile "$env:USERPROFILE\Downloads\kafka.tgz" -UseBasicParsing

# Extract to home folder
tar -xzf "$env:USERPROFILE\Downloads\kafka.tgz" -C "$env:USERPROFILE"
Rename-Item "$env:USERPROFILE\kafka_2.13-3.9.2" "$env:USERPROFILE\kafka"
```

Fix the Windows 11 `wmic` bug in Kafka's startup script — open this file in Notepad:

```
C:\Users\<you>\kafka\bin\windows\kafka-server-start.bat
```

Find this block (around line 28):
```bat
for /f "tokens=*" %%i in ('wmic os get osarchitecture') do ...
```
Replace the **entire** `IF` block with this one line:
```bat
set KAFKA_HEAP_OPTS=-Xmx1G -Xms1G
```
Do the same in `kafka-server-stop.bat`.

Format Kafka storage (KRaft mode — no ZooKeeper):

```powershell
# Update log path in server.properties
# Open: %USERPROFILE%\kafka\config\kraft\server.properties
# Change:  log.dirs=/tmp/kraft-combined-logs
# To:      log.dirs=C:/Users/<you>/kafka-logs

# Generate cluster ID and format storage
$uuid = & "$env:USERPROFILE\kafka\bin\windows\kafka-storage.bat" random-uuid
& "$env:USERPROFILE\kafka\bin\windows\kafka-storage.bat" format `
    --config "$env:USERPROFILE\kafka\config\kraft\server.properties" `
    --cluster-id $uuid
```

### Step 5 — Install winutils (for Spark on Windows)

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\hadoop\bin"

Invoke-WebRequest `
  -Uri "https://github.com/cdarlint/winutils/raw/master/hadoop-3.3.6/bin/winutils.exe" `
  -OutFile "$env:USERPROFILE\hadoop\bin\winutils.exe" -UseBasicParsing

Invoke-WebRequest `
  -Uri "https://github.com/cdarlint/winutils/raw/master/hadoop-3.3.6/bin/hadoop.dll" `
  -OutFile "$env:USERPROFILE\hadoop\bin\hadoop.dll" -UseBasicParsing

[System.Environment]::SetEnvironmentVariable("HADOOP_HOME","$env:USERPROFILE\hadoop","User")
```

### Step 6 — Run the app

**Option A — One-click launcher (recommended):**

```
Double-click  START_APP.bat
```

Automatically starts Kafka, waits for broker, launches Streamlit at `http://localhost:8501`.

**Option B — Manual (two terminals):**

```powershell
# Terminal 1 — Start Kafka
$env:KAFKA_HEAP_OPTS = "-Xmx1G -Xms1G"
& "$env:USERPROFILE\kafka\bin\windows\kafka-server-start.bat" `
  "$env:USERPROFILE\kafka\config\kraft\server.properties"

# Terminal 2 — Start app
$env:PYTHONIOENCODING = "utf-8"
$env:HADOOP_HOME = "$env:USERPROFILE\hadoop"
python -m streamlit run app.py
```

---

## ⚡ Quick Comparison — Mac vs Windows

| Task | Mac | Windows |
|------|-----|---------|
| Install Java | `brew install --cask temurin` | Download from adoptium.net |
| Install Kafka | `curl` + `tar` | `Invoke-WebRequest` + `tar` |
| Kafka scripts | `.sh` files in `bin/` | `.bat` files in `bin/windows/` |
| winutils | ❌ Not needed | ✅ Required for Spark |
| Launch app | `./start_app.sh` | `START_APP.bat` |
| Python command | `python3` | `python` |
| Spark | Works natively | Needs winutils |

---

## 📁 Project Structure

```
Real-Time-Online-Delivery-Price-Comparison/
│
├── app.py                        ← Streamlit dashboard (entry point)
├── START_APP.bat                 ← One-click launcher for Windows
├── start_app.sh                  ← One-click launcher for Mac / Linux
├── requirements.txt              ← pip dependencies
├── README.md                     ← This file
│
├── src/
│   ├── scraper/
│   │   ├── base.py               ← BaseScraper + Chrome driver (cross-platform UA)
│   │   ├── amazon.py             ← Amazon Fresh   ✅ Active
│   │   ├── blinkit.py            ← Blinkit         ✅ Active
│   │   ├── bigbasket.py          ← BigBasket        ✅ Active
│   │   ├── zepto.py              ← Zepto            ✅ Active
│   │   ├── flipkart.py           ← Flipkart         ⏳ Future
│   │   ├── instamart.py          ← Swiggy Instamart ⏳ Future
│   │   ├── manager.py            ← Orchestrates all scrapers
│   │   └── delivery.py           ← Pincode → city mapping
│   │
│   ├── pipeline/
│   │   ├── kafka_pipeline.py     ← Kafka producer + consumer
│   │   └── spark_processor.py    ← Rank · ₹/unit · Pandas fallback
│   │
│   └── database/
│       └── db.py                 ← SQLite storage
│
└── data/
    └── prices.db                 ← SQLite DB (auto-created on first run)
```

---

## 🌐 Active Platforms

| Platform | Method | Status |
|----------|--------|--------|
| **Amazon Fresh** | HTML card parse | ✅ Active |
| **Blinkit** | Selenium + HTML | ✅ Active |
| **BigBasket** | `__NEXT_DATA__` JSON | ✅ Active |
| **Zepto** | localStorage injection | ✅ Active |
| **Flipkart** | HTML | ⏳ Future |
| **Swiggy Instamart** | Cookie injection | ⏳ Future |

---

## 📍 Supported Pincodes

| City | Prefix | Example |
|------|--------|---------|
| Bangalore | 560, 562 | `560001` |
| Delhi | 110 | `110001` |
| Mumbai | 400, 401 | `400001` |
| Hyderabad | 500 | `500001` |
| Chennai | 600 | `600001` |
| Kolkata | 700 | `700001` |
| Pune | 411 | `411001` |
| Ahmedabad | 380 | `380001` |
| Gurugram | 122 | `122001` |
| Noida | 201 | `201301` |
| Jaipur | 302 | `302001` |
| Lucknow | 226 | `226001` |
| Chandigarh | 160 | `160017` |
| Indore | 452 | `452001` |

---

## 🔧 Troubleshooting

### Chrome not found
```bash
# webdriver-manager auto-downloads the right ChromeDriver
# Just make sure Google Chrome is installed
```

### Kafka not connecting
```
[Kafka] Broker not available — using in-memory fallback
```
App works fine without Kafka. To fix: follow the Kafka setup steps above.

### Spark not starting (shows "Pandas fallback")
Java 11+ must be installed and on PATH. Check with:
```bash
java -version
```
App still works — Pandas runs the same logic as Spark.

### Mac: `permission denied` on start_app.sh
```bash
chmod +x start_app.sh
./start_app.sh
```

### Windows: ₹ symbol shows as `?`
Use `START_APP.bat` — it sets `PYTHONIOENCODING=utf-8` automatically.

### Windows: `wmic` not recognised when starting Kafka
Edit `kafka-server-start.bat` and replace the `wmic` block with:
```bat
set KAFKA_HEAP_OPTS=-Xmx1G -Xms1G
```

---

## ⚙️ Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Scraping | Selenium + webdriver-manager | 4.x |
| HTML parsing | BeautifulSoup4 + lxml | 4.12 |
| Message queue | Apache Kafka (KRaft) | 3.9.2 |
| Kafka client | kafka-python | 2.0.2 |
| Processing | Apache Spark / Pandas | 4.x / 2.x |
| Storage | SQLite | built-in |
| Dashboard | Streamlit | 1.32+ |
| Charts | Plotly Express | 5.x |
| Language | Python | 3.10+ |

---

## ⚠️ Disclaimer

This project is for **educational purposes** — demonstrating a real-time data engineering pipeline using industry-standard tools. Scraping websites may violate their Terms of Service. Use responsibly and do not run in a production or commercial environment.

---

*Data Engineering Project — Selenium · Apache Kafka · Apache Spark · SQLite · Streamlit*
