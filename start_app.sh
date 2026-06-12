#!/usr/bin/env bash
# ============================================================
#  Real-Time Indian Grocery Price Comparison
#  Mac / Linux Launcher  —  equivalent of START_APP.bat
#  Usage:  chmod +x start_app.sh && ./start_app.sh
# ============================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo "  Real-Time Indian Grocery Price Comparison"
echo "  Data Engineering Pipeline Launcher (Mac / Linux)"
echo "============================================================"
echo ""

# ── Kafka home ────────────────────────────────────────────────
KAFKA_HOME="${KAFKA_HOME:-$HOME/kafka}"

if [ ! -f "$KAFKA_HOME/bin/kafka-server-start.sh" ]; then
    echo "[WARN] Kafka not found at $KAFKA_HOME"
    echo "       See README.md — 'Kafka Setup (Mac)' section."
    echo "       App will still run using in-memory fallback."
    echo ""
else
    # ── 1. Stop any old Kafka broker ─────────────────────────
    echo "[1/3] Checking for old Kafka processes..."
    OLD_PID=$(pgrep -f "kafka.Kafka" 2>/dev/null || true)
    if [ -n "$OLD_PID" ]; then
        echo "  Stopping old Kafka PID=$OLD_PID..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 3
    fi

    # ── 2. Start Kafka broker ─────────────────────────────────
    echo "[1/3] Starting Apache Kafka broker (KRaft mode)..."
    export KAFKA_HEAP_OPTS="-Xmx1G -Xms1G"

    nohup "$KAFKA_HOME/bin/kafka-server-start.sh" \
          "$KAFKA_HOME/config/kraft/server.properties" \
          > "$HOME/kafka-server.log" 2>&1 &

    echo "  Waiting 20 seconds for broker to be ready..."
    sleep 20

    # Quick connectivity test
    python3 -c "
from kafka import KafkaProducer
try:
    p = KafkaProducer(bootstrap_servers='localhost:9092',
                      request_timeout_ms=3000, max_block_ms=3000)
    p.close()
    print('  [OK] Kafka ready at localhost:9092')
except Exception as e:
    print(f'  [WARN] Kafka may still be starting — in-memory fallback will be used')
" 2>/dev/null || true
    echo ""
fi

# ── 3. Environment ────────────────────────────────────────────
echo "[2/3] Setting environment..."
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
echo "  PYTHONIOENCODING = utf-8"
echo ""

# ── 4. Launch Streamlit ───────────────────────────────────────
echo "[3/3] Launching Streamlit app..."
echo ""
echo "============================================================"
echo "  App URL  : http://localhost:8501"
echo "  Kafka    : localhost:9092  (KRaft, no ZooKeeper)"
echo "  Spark    : local[2]       (Apache Spark 4.x)"
echo ""
echo "  Press Ctrl+C to stop."
echo "============================================================"
echo ""

python3 -m streamlit run app.py --server.port 8501
