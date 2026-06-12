"""
db.py
-----
SQLite database layer.
- No MySQL setup needed — SQLite is built into Python
- Stores every search result with timestamp + query + pincode
- Query history so teacher can see data accumulates over searches

Database file: data/prices.db
"""

import sqlite3
import os
import json
from datetime import datetime
from typing import List, Dict, Callable, Optional

ROOT    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(ROOT, "data", "prices.db")


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS searches (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            query       TEXT    NOT NULL,
            pincode     TEXT    NOT NULL,
            result_count INTEGER DEFAULT 0,
            searched_at TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS prices (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            search_id       INTEGER REFERENCES searches(id),
            platform        TEXT,
            product_name    TEXT,
            brand           TEXT,
            price           REAL,
            mrp             REAL,
            discount_pct    REAL,
            quantity        TEXT,
            unit            TEXT,
            size_label      TEXT,
            price_per_unit  REAL,
            unit_norm       TEXT,
            delivery_mins   INTEGER,
            in_stock        INTEGER,
            rank            INTEGER,
            savings         REAL,
            is_best_deal    INTEGER,
            pincode         TEXT,
            source          TEXT,
            scraped_at      TEXT,
            processed_at    TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_prices_query
            ON prices (product_name, pincode, scraped_at);
        """)


class Database:
    def __init__(self, log_callback: Callable):
        self.log = log_callback
        init_db()

    # ── Save ───────────────────────────────────────────────────────────────────
    def save(self, products: List[Dict], query: str, pincode: str) -> int:
        self.log("\n" + "=" * 52)
        self.log("PHASE 4 — DATABASE STORAGE")
        self.log(f"Database: SQLite  ({DB_PATH})")
        self.log(f"Records : {len(products)}")
        self.log("=" * 52)

        if not products:
            self.log("  [DB] No records to save")
            return 0

        now = datetime.now().isoformat()
        with _conn() as c:
            # Insert search record
            cur = c.execute(
                "INSERT INTO searches (query, pincode, result_count, searched_at) VALUES (?,?,?,?)",
                (query, pincode, len(products), now),
            )
            search_id = cur.lastrowid
            self.log(f"  [DB] Search record created — search_id={search_id}")

            # Insert all product records
            rows = []
            for p in products:
                rows.append((
                    search_id,
                    p.get("platform"),
                    p.get("product_name"),
                    p.get("brand"),
                    p.get("price"),
                    p.get("mrp"),
                    p.get("discount_pct"),
                    p.get("quantity"),
                    p.get("unit"),
                    p.get("size_label"),
                    p.get("price_per_unit"),
                    p.get("unit_norm"),
                    p.get("delivery_mins"),
                    int(bool(p.get("in_stock", True))),
                    p.get("rank", 1),
                    p.get("savings", 0.0),
                    int(bool(p.get("is_best_deal", False))),
                    p.get("pincode"),
                    p.get("source", "LIVE"),
                    p.get("scraped_at"),
                    p.get("processed_at"),
                ))

            c.executemany("""
                INSERT INTO prices (
                    search_id, platform, product_name, brand,
                    price, mrp, discount_pct,
                    quantity, unit, size_label,
                    price_per_unit, unit_norm,
                    delivery_mins, in_stock,
                    rank, savings, is_best_deal,
                    pincode, source, scraped_at, processed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, rows)

        self.log(f"  [DB] ✅ {len(rows)} price records inserted")
        self.log(f"  [DB] Table: prices  (search_id={search_id})")
        self.log(f"  [DB] Table: searches (id={search_id})")

        # Show DB stats
        stats = self._stats()
        self.log(f"  [DB] Total records in DB: {stats['total_prices']}")
        self.log(f"  [DB] Total searches in DB: {stats['total_searches']}")
        self.log(f"  [DB] DB file size: {stats['db_size_kb']} KB")
        return len(rows)

    # ── Query ──────────────────────────────────────────────────────────────────
    def get_latest(self, query: str, pincode: str, limit: int = 200) -> List[Dict]:
        """Get most recent results for a query+pincode."""
        with _conn() as c:
            rows = c.execute("""
                SELECT p.* FROM prices p
                JOIN searches s ON p.search_id = s.id
                WHERE s.query   = ?
                  AND s.pincode = ?
                ORDER BY p.rank ASC, p.price ASC
                LIMIT ?
            """, (query, pincode, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_history(self) -> List[Dict]:
        """Return all past searches."""
        with _conn() as c:
            rows = c.execute("""
                SELECT id, query, pincode, result_count, searched_at
                FROM searches
                ORDER BY id DESC
                LIMIT 20
            """).fetchall()
        return [dict(r) for r in rows]

    def _stats(self) -> Dict:
        with _conn() as c:
            total_prices   = c.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
            total_searches = c.execute("SELECT COUNT(*) FROM searches").fetchone()[0]
        size_kb = round(os.path.getsize(DB_PATH) / 1024, 1) if os.path.exists(DB_PATH) else 0
        return {
            "total_prices":   total_prices,
            "total_searches": total_searches,
            "db_size_kb":     size_kb,
        }
