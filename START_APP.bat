@echo off
title Grocery Price Compare — Startup
color 0A

echo ============================================================
echo   Real-Time Indian Grocery Price Comparison
echo   Data Engineering Pipeline Launcher
echo ============================================================
echo.

:: ── Check KAFKA_HOME ─────────────────────────────────────────
if "%KAFKA_HOME%"=="" (
    set KAFKA_HOME=%USERPROFILE%\kafka
)
if not exist "%KAFKA_HOME%\bin\windows\kafka-server-start.bat" (
    echo [WARN] Kafka not found at %KAFKA_HOME%
    echo        See README.md -- "Kafka Setup" section to install.
    echo        App will still run using in-memory fallback.
    echo.
    goto :start_app
)

:: ── 1. Start Kafka broker ────────────────────────────────────
echo [1/3] Starting Apache Kafka broker (KRaft mode)...
set KAFKA_HEAP_OPTS=-Xmx1G -Xms1G
set HADOOP_HOME=%USERPROFILE%\hadoop

:: Kill any old Kafka java process
for /f "tokens=1" %%P in ('jps -l 2^>nul ^| findstr "kafka"') do (
    echo   Stopping old Kafka process PID=%%P...
    taskkill /PID %%P /F >nul 2>&1
)

:: Start Kafka in a minimized background window
start "Kafka Broker [do not close]" /MIN cmd /c ^
  "set KAFKA_HEAP_OPTS=-Xmx1G -Xms1G && ^
   "%KAFKA_HOME%\bin\windows\kafka-server-start.bat" ^
   "%KAFKA_HOME%\config\kraft\server.properties" ^
   > "%USERPROFILE%\kafka-server.log" 2>&1"

echo   Waiting 20 seconds for broker to be ready...
timeout /t 20 /nobreak >nul

python -c "from kafka import KafkaProducer; p=KafkaProducer(bootstrap_servers='localhost:9092',request_timeout_ms=3000,max_block_ms=3000); p.close(); print('  [OK] Kafka ready at localhost:9092')" 2>nul
if not %ERRORLEVEL%==0 (
    echo   [WARN] Kafka may still be starting — app will use in-memory fallback if needed
)
echo.

:: ── 2. Environment variables ─────────────────────────────────
:start_app
echo [2/3] Setting environment...
set HADOOP_HOME=%USERPROFILE%\hadoop
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
echo   HADOOP_HOME     = %HADOOP_HOME%
echo   PYTHONIOENCODING = utf-8
echo.

:: ── 3. Launch Streamlit ───────────────────────────────────────
echo [3/3] Launching Streamlit app...
echo.
echo ============================================================
echo   App URL  : http://localhost:8501
echo   Kafka    : localhost:9092  (KRaft, no ZooKeeper)
echo   Spark    : local[2]       (Apache Spark 4.1.2)
echo.
echo   Press Ctrl+C to stop.
echo ============================================================
echo.

streamlit run app.py --server.port 8501
