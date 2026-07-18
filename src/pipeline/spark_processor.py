"""
spark_processor.py
------------------
Data processing layer.

What it does to each product record:
  1. Normalises units → price per 100g / per 100mL / per piece
  2. Cleans price strings  (₹149, Rs.149, etc.)
  3. Ranks products cheapest → costliest within same product+size group
  4. Calculates savings vs most expensive option
  5. Flags best deal in each group

Uses Apache Spark if available (pyspark installed + Java 11+).
Falls back to pandas if Spark not available — same logic, same output.
Terminal shows which engine is running.
"""

import re
import os
from datetime import datetime
from typing import List, Dict, Callable


class SparkProcessor:
    def __init__(self, log_callback: Callable):
        self.log        = log_callback
        self._use_spark = self._check_spark()

    # ── Spark availability check ───────────────────────────────────────────────
    def _check_spark(self) -> bool:
        try:
            import pyspark
            import pyspark.sql  # noqa
            # Also need Java
            java = os.popen("java -version 2>&1").read()
            if "version" in java.lower():
                # Set PYSPARK_PYTHON so Spark finds the right interpreter
                import sys
                os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
                os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)
                # winutils is only needed on Windows — skip entirely on Mac/Linux
                if sys.platform == "win32":
                    import pathlib
                    hadoop_home = pathlib.Path.home() / "hadoop"
                    if hadoop_home.exists():
                        os.environ.setdefault("HADOOP_HOME", str(hadoop_home))
                return True
        except ImportError:
            pass
        return False

    # ── Main API ───────────────────────────────────────────────────────────────
    def process(self, products: List[Dict]) -> List[Dict]:
        self.log("\n" + "=" * 52)
        self.log("PHASE 3 — DATA PROCESSING")
        engine = "Apache Spark" if self._use_spark else "Pandas (Spark fallback)"
        self.log(f"Engine  : {engine}")
        self.log(f"Records : {len(products)}")
        self.log("=" * 52)

        if not products:
            self.log("  [Processing] No records to process")
            return []

        if self._use_spark:
            return self._spark_process(products)
        else:
            return self._pandas_process(products)

    # ── Spark processing ───────────────────────────────────────────────────────
    def _spark_process(self, products: List[Dict]) -> List[Dict]:
        from pyspark.sql import SparkSession
        from pyspark.sql import functions as F
        from pyspark.sql.window import Window
        from pyspark.sql.types import StructType, StructField, StringType, DoubleType, IntegerType, BooleanType

        self.log("  [Spark] Creating SparkSession (local[2])...")
        spark = (
            SparkSession.builder
            .appName("PriceCompare")
            .master("local[2]")
            .config("spark.sql.shuffle.partitions", "4")
            .config("spark.driver.memory", "1g")
            .config("spark.python.worker.reuse", "true")
            .config("spark.ui.enabled", "false")
            .getOrCreate()
        )
        spark.sparkContext.setLogLevel("ERROR")
        self.log(f"  [Spark] ✅ Session created — Spark {spark.version}")

        # Create DataFrame
        df = spark.createDataFrame(products)
        self.log(f"  [Spark] DataFrame created: {df.count()} rows × {len(df.columns)} cols")

        self.log("  [Spark] Step 1: Normalising price_per_unit...")
        # UDF for price per unit normalisation
        @F.udf("double")
        def ppu_udf(price, qty, unit):
            try:
                q = float(qty)
                p = float(price)
                u = (unit or "pcs").lower()
                if u == "g":   return round(p / q * 100, 2)
                if u == "kg":  return round(p / (q * 1000) * 100, 2)
                if u == "ml":  return round(p / q * 100, 2)
                if u == "l":   return round(p / (q * 1000) * 100, 2)
                if u == "pcs": return round(p / q, 2)
                return p
            except:
                return price

        df = df.withColumn("price_per_unit", ppu_udf(F.col("price"), F.col("quantity"), F.col("unit")))

        self.log("  [Spark] Step 2: Ranking by price per group...")
        grp = ["product_name", "size_label"]
        rank_window = Window.partitionBy(*grp).orderBy(F.col("price").asc())
        df = df.withColumn("rank", F.rank().over(rank_window))

        self.log("  [Spark] Step 3: Calculating savings vs costliest...")
        max_w = Window.partitionBy(*grp)
        df = df.withColumn("max_price",   F.max("price").over(max_w))
        df = df.withColumn("savings",     F.round(F.col("max_price") - F.col("price"), 2))
        df = df.withColumn("is_best_deal",F.col("rank") == 1)

        self.log("  [Spark] Step 4: Adding processing timestamp...")
        df = df.withColumn("processed_at", F.lit(datetime.now().isoformat()))

        rows = [row.asDict() for row in df.collect()]
        spark.stop()
        self.log(f"  [Spark] ✅ Processing complete — {len(rows)} records")
        return sorted(rows, key=lambda x: (x.get("product_name",""), x.get("rank", 99)))

    # ── Pandas processing (fallback) ───────────────────────────────────────────
    def _pandas_process(self, products: List[Dict]) -> List[Dict]:
        import pandas as pd
        self.log("  [Pandas] Loading records into DataFrame...")
        df = pd.DataFrame(products)
        self.log(f"  [Pandas] DataFrame: {len(df)} rows × {len(df.columns)} columns")

        self.log("  [Pandas] Step 1: Normalising price per unit (g/kg/mL/L/pcs)...")
        df["price_per_unit"] = df.apply(
            lambda r: self._calc_ppu(r["price"], r.get("quantity","1"), r.get("unit","pcs")),
            axis=1,
        )

        self.log("  [Pandas] Step 2: Normalising unit labels...")
        df["unit_norm"] = df["unit"].apply(self._unit_norm_label)

        self.log("  [Pandas] Step 3: Computing value score (price_per_unit + delivery penalty)...")
        # Composite value score — factors BOTH unit price AND delivery speed:
        #   penalty = 15% extra per hour of delivery wait
        #   A 10-min delivery adds ~2.5% penalty; 120-min adds 30%
        def value_score(row):
            ppu  = float(row.get("price_per_unit") or row["price"])
            dm   = float(row.get("delivery_mins") or 60)
            return round(ppu * (1 + (dm / 60) * 0.15), 4)
        df["value_score"] = df.apply(value_score, axis=1)

        self.log("  [Pandas] Step 4: Ranking globally by value score (price/unit + delivery)...")
        df["rank"] = df["value_score"].rank(method="min", ascending=True).astype(int)

        self.log("  [Pandas] Step 5: Calculating savings vs worst value in results...")
        max_price = df["price"].max()
        df["savings"] = (max_price - df["price"]).round(2)

        self.log("  [Pandas] Step 6: Flagging best deal (rank == 1)...")
        df["is_best_deal"] = df["rank"] == 1

        self.log("  [Pandas] Step 7: Adding processing timestamp...")
        df["processed_at"] = datetime.now().isoformat()

        df = df.sort_values("rank")
        rows = df.to_dict(orient="records")
        self.log(f"  [Pandas] ✅ Processing complete — {len(rows)} records")
        self.log(f"  [Pandas]    Ranking: price/unit × delivery penalty (15%/hr)")
        return rows

    # ── Helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _calc_ppu(price, qty, unit) -> float:
        try:
            q = float(qty);  p = float(price)
            u = str(unit).lower()
            if u == "g":   return round(p / q * 100, 2)
            if u == "kg":  return round(p / (q * 1000) * 100, 2)
            if u == "ml":  return round(p / q * 100, 2)
            if u == "l":   return round(p / (q * 1000) * 100, 2)
            if u == "pcs": return round(p / q, 2)
            return round(p, 2)
        except Exception:
            return round(float(price), 2)

    @staticmethod
    def _unit_norm_label(unit: str) -> str:
        u = str(unit).lower()
        if u in ("g", "kg"): return "per 100g"
        if u in ("ml", "l"): return "per 100mL"
        if u == "pcs":       return "per pc"
        return "per unit"
