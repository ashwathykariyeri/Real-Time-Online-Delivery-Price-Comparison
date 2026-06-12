# ═══════════════════════════════════════════════════════════════════════
#  Dockerfile — Multi-stage build
#  Stage 1: base       — Python 3.11 + common dependencies
#  Stage 2: ml-api     — FastAPI inference server
#  Stage 3: streamlit  — Streamlit dashboard
# ═══════════════════════════════════════════════════════════════════════

# ── Stage 1: Base ─────────────────────────────────────────────────────
FROM python:3.11-slim AS base

LABEL maintainer="price-compare-india"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    g++ \
    libmariadb-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install \
        streamlit==1.32.0 \
        plotly==5.20.0 \
        pandas==2.2.1 \
        numpy==1.26.4 \
        scikit-learn==1.4.1 \
        mlflow==2.11.1 \
        joblib==1.3.2 \
        fastapi==0.110.0 \
        uvicorn==0.27.1 \
        httpx==0.27.0 \
        mysql-connector-python==8.3.0 \
        SQLAlchemy==2.0.27 \
        pymysql==1.1.0 \
        kafka-python==2.0.2 \
        python-dotenv==1.0.1 \
        pyyaml==6.0.1 \
        requests==2.31.0 \
        beautifulsoup4==4.12.3 \
        lxml==5.1.0 \
        fake-useragent==1.4.0

COPY . .

# ── Stage 2: ML API ───────────────────────────────────────────────────
FROM base AS ml-api

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "src/processing/ml_api.py"]

# ── Stage 3: Streamlit ────────────────────────────────────────────────
FROM base AS streamlit

EXPOSE 8501

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "src/frontend/app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
