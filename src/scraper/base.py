"""
base.py
-------
Base class for Selenium scrapers.
- Headless Chrome via webdriver-manager (auto-downloads correct ChromeDriver)
- Browser-like fingerprint so pages render properly
- NO offline cache — if a scraper finds nothing, it returns []
- Fields returned: platform, product_name, price, brand, description, source
"""

import json
import re
import time
import os
from datetime import datetime
from typing import List, Dict, Callable, Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup


def build_chrome_driver(log_fn: Callable = print) -> webdriver.Chrome:
    """Create a headless Chrome driver with browser-like settings."""
    import sys
    from webdriver_manager.chrome import ChromeDriverManager

    # Match User-Agent to actual OS so sites render properly
    _ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        if sys.platform == "darwin" else
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    opts = Options()
    opts.add_argument("--headless=new")          # modern headless mode
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument(f"--user-agent={_ua}")
    opts.add_argument("--lang=en-IN")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--log-level=3")           # suppress Chrome's own logs

    log_fn("  [Chrome] Launching headless Chrome...")
    service = Service(ChromeDriverManager().install())
    driver  = webdriver.Chrome(service=service, options=opts)

    # Mask webdriver flag (basic anti-bot bypass)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"}
    )
    log_fn("  [Chrome] ✅ Browser ready")
    return driver


class BaseScraper:
    """All platform scrapers inherit from this."""
    platform      = "Unknown"
    delivery_mins = None   # subclasses set this to a real estimate

    def __init__(self, log_callback: Callable):
        self.log      = log_callback
        self._pincode = ""   # set by scrape() before calling _fetch()

    # ── called by manager ──────────────────────────────────────────────────────
    def scrape(self, query: str, driver: webdriver.Chrome,
               pincode: str = "", screenshot_dir: str = "") -> List[Dict]:
        self._pincode = pincode
        self.log(f"\n  ── {self.platform} ──")
        t0 = time.time()
        try:
            results = self._fetch(query, driver)
            # Screenshot after fetch — captures the live search results page
            if screenshot_dir:
                self._save_screenshot(driver, screenshot_dir)
            elapsed = round(time.time() - t0, 2)
            self.log(f"  [{self.platform}] ✅ {len(results)} products  ({elapsed}s)")
            return results
        except Exception as e:
            # Try screenshot even on failure (shows the error/blocked page)
            if screenshot_dir:
                try: self._save_screenshot(driver, screenshot_dir)
                except Exception: pass
            elapsed = round(time.time() - t0, 2)
            self.log(f"  [{self.platform}] ❌ {type(e).__name__}: {str(e)[:80]}  ({elapsed}s)")
            return []

    def _save_screenshot(self, driver: webdriver.Chrome, screenshot_dir: str) -> str:
        """Take a full-page screenshot of the current browser state."""
        try:
            os.makedirs(screenshot_dir, exist_ok=True)
            slug = re.sub(r"[^\w]", "_", self.platform.lower())
            path = os.path.join(screenshot_dir, f"{slug}.png")
            driver.save_screenshot(path)
            self.log(f"  [{self.platform}] 📸 Screenshot saved")
            return path
        except Exception as e:
            self.log(f"  [{self.platform}] Screenshot skipped: {e}")
            return ""

    # ── subclasses override this ───────────────────────────────────────────────
    def _fetch(self, query: str, driver: webdriver.Chrome) -> List[Dict]:
        raise NotImplementedError

    # ── helpers ────────────────────────────────────────────────────────────────
    def _get_page(self, driver: webdriver.Chrome, url: str,
                  wait_selector: str, timeout: int = 15) -> BeautifulSoup:
        """Load URL and wait for a CSS selector to appear, then return soup."""
        self.log(f"  [{self.platform}] → {url[:80]}")
        driver.get(url)
        try:
            WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector))
            )
        except Exception:
            pass   # continue even if wait times out — parse whatever loaded
        time.sleep(1)   # let lazy images / price elements settle
        return BeautifulSoup(driver.page_source, "html.parser")

    def _next_data(self, driver: webdriver.Chrome) -> Optional[dict]:
        """Extract __NEXT_DATA__ JSON from current page (Next.js sites)."""
        try:
            tag = driver.find_element(By.ID, "__NEXT_DATA__")
            return json.loads(tag.get_attribute("innerHTML"))
        except Exception:
            return None

    @staticmethod
    def _clean_price(text: str) -> Optional[float]:
        """Parse price string like '₹65', 'Rs.65', '65.00' → float."""
        if not text:
            return None
        s = re.sub(r"[^\d.]", "", text.replace(",", ""))
        try:
            v = float(s)
            return v if v > 0 else None
        except ValueError:
            return None

    # ── Size/unit extraction ───────────────────────────────────────────────────
    _SIZE_RE = re.compile(
        r"(?<!\w)"                             # not preceded by a letter/digit
        r"(\d+(?:\.\d+)?)"                     # number (int or decimal)
        r"\s*"                                 # optional space
        r"(kg|grams?|gms?|g"                   # weight: kg first, then g variants
        r"|litres?|liters?|lit|l"              # volume large: long forms before bare l
        r"|ml)"                                # volume small
        r"(?!\w)",                             # not followed by a letter/digit
        flags=re.I,
    )

    @classmethod
    def _extract_size(cls, product_name: str) -> tuple:
        """
        Parse size/weight/volume from a product name string.
        Returns (quantity_str, unit_str, size_label_str).
        e.g. 'Amul Milk 500 ml'  → ('500', 'ml',  '500ml')
             'Sugar 1 kg'         → ('1',   'kg',  '1kg')
             'Eggs 12 pcs'        → ('12',  'pcs', '12 pcs')
             'Plain Yogurt'       → ('1',   'pcs', '')
        """
        m = cls._SIZE_RE.search(product_name)
        if m:
            qty_str  = m.group(1)
            raw_unit = m.group(2).lower()
            # Normalise to canonical unit
            if raw_unit == "kg":
                unit = "kg"
            elif raw_unit in ("g", "gm", "gms", "gram", "grams"):
                unit = "g"
            elif raw_unit in ("l", "lit", "litre", "liter", "litres", "liters"):
                unit = "l"
            elif raw_unit == "ml":
                unit = "ml"
            else:
                unit = raw_unit
            label = f"{qty_str}{unit}"
            return (qty_str, unit, label)

        # Try pcs / pack pattern (e.g. "6 pcs", "pack of 12")
        pcs_m = re.search(r"(?:pack\s+of\s+|x\s*)?(\d+)\s*(?:pcs?|pieces?|eggs?|units?)",
                          product_name, re.I)
        if pcs_m:
            qty_str = pcs_m.group(1)
            return (qty_str, "pcs", f"{qty_str} pcs")

        return ("1", "pcs", "")

    def _build(self, product_name: str, price: float,
               brand: str = "", description: str = "",
               mrp: float = 0.0) -> Dict:
        """Return a standardised product record — only real fields."""
        name = product_name.strip()[:120]

        # Auto-extract size from product name if not caller-supplied
        qty_str, unit, size_label = self._extract_size(name)
        qty = float(qty_str)

        # Price per unit
        try:
            p = float(price)
            u = unit.lower()
            if u == "g":     ppu = round(p / qty * 100, 2)   # per 100g
            elif u == "kg":  ppu = round(p / (qty * 1000) * 100, 2)
            elif u == "ml":  ppu = round(p / qty * 100, 2)   # per 100ml
            elif u == "l":   ppu = round(p / (qty * 1000) * 100, 2)
            else:            ppu = round(p / qty, 2)          # per pc
        except Exception:
            ppu = round(price, 2)

        # Unit display label
        u = unit.lower()
        if u in ("g", "kg"):    unit_norm = "per 100g"
        elif u in ("ml", "l"):  unit_norm = "per 100mL"
        else:                   unit_norm = "per pc"

        # MRP / discount
        effective_mrp = mrp if mrp and mrp > price else price
        disc = round((effective_mrp - price) / effective_mrp * 100, 1) if effective_mrp > price else 0.0

        return {
            "platform":       self.platform,
            "product_name":   name,
            "price":          round(price, 2),
            "brand":          brand.strip()[:60],
            "description":    description.strip()[:200],
            "source":         "LIVE",
            "scraped_at":     datetime.now().isoformat(),
            "mrp":            round(effective_mrp, 2),
            "discount_pct":   disc,
            "quantity":       qty_str,
            "unit":           unit,
            "size_label":     size_label,
            "price_per_unit": ppu,
            "unit_norm":      unit_norm,
            "delivery_mins":  self.delivery_mins,
            "in_stock":       True,
            "pincode":        "",
            "product_url":    "",   # scrapers set this to the actual product page URL
        }
