"""
zepto.py
--------
Zepto Selenium scraper.

Key findings (live diagnostic):
  - Real domain: zepto.com  (NOT zeptonow.com — that redirects here)
  - Location is stored in localStorage key: "user-position"
  - Structure: {"state":{"userPosition":{...},"userGpsCoords":{lat,lng},...}}
  - Injecting Bangalore coords before loading search → 86+ price elements appear

Strategy:
  1. Load https://www.zepto.com/ to seed cookies/session
  2. Inject latitude/longitude for user's pincode into localStorage
  3. Navigate to https://www.zepto.com/search?query={query}
  4. Parse product cards from rendered HTML
"""

import re
import json
import time
from datetime import datetime
from typing import List, Dict, Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup

from .base import BaseScraper

HOMEPAGE   = "https://www.zepto.com/"
SEARCH_URL = "https://www.zepto.com/search?query={query}"

# Pincode prefix → (lat, lng, place_id, description)
_LOCATION = {
    "560": (12.9716, 77.5946, "ChIJbU60yXAWrjsR4E9-UejD3_g", "Bangalore, Karnataka, India"),
    "562": (12.9716, 77.5946, "ChIJbU60yXAWrjsR4E9-UejD3_g", "Bangalore, Karnataka, India"),
    "110": (28.6139, 77.2090, "ChIJLbZ-efUCDTkRzWe1mMOeKKM", "New Delhi, Delhi, India"),
    "122": (28.4595, 77.0266, "ChIJ0X31pIkEDTkRZiVa7LTaLuA", "Gurugram, Haryana, India"),
    "201": (28.5355, 77.3910, "ChIJezVzMaTlDDkRP8B8yDDO_zc", "Noida, Uttar Pradesh, India"),
    "400": (19.0760, 72.8777, "ChIJwe1EZjDG5zsRmKl57UfxfEA", "Mumbai, Maharashtra, India"),
    "401": (19.0760, 72.8777, "ChIJwe1EZjDG5zsRmKl57UfxfEA", "Mumbai, Maharashtra, India"),
    "411": (18.5204, 73.8567, "ChIJARFGZy6_wjsRQ-Kcrmn_aPs", "Pune, Maharashtra, India"),
    "500": (17.3850, 78.4867, "ChIJx9Lr6tqZyzsRwuu6hwd9abM", "Hyderabad, Telangana, India"),
    "600": (13.0827, 80.2707, "ChIJYeZuBI9WUjoRM9MI6UYXAQs", "Chennai, Tamil Nadu, India"),
    "700": (22.5726, 88.3639, "ChIJZ_YISduC-DkRvCxsj-Yw40M", "Kolkata, West Bengal, India"),
    "380": (23.0225, 72.5714, "ChIJSdRbuoqEXjkRFmVPYRHdzk8", "Ahmedabad, Gujarat, India"),
    "302": (26.9124, 75.7873, "ChIJD4CXMwCXdDkRMxMixNrwTHE", "Jaipur, Rajasthan, India"),
    "226": (26.8467, 80.9462, "ChIJr3YSj2Sa7zkRpFjlLmDHcwA", "Lucknow, Uttar Pradesh, India"),
    "160": (30.7333, 76.7794, "ChIJi3ksM3fUGTkRlkfTGqitOkM", "Chandigarh, India"),
    "452": (22.7196, 75.8577, "ChIJCf_kFhVkfDkRW4bTsDVS8iw", "Indore, Madhya Pradesh, India"),
}
_DEFAULT = (12.9716, 77.5946, "ChIJbU60yXAWrjsR4E9-UejD3_g", "Bangalore, Karnataka, India")


class ZeptoScraper(BaseScraper):
    platform      = "Zepto"
    delivery_mins = 10

    def _fetch(self, query: str, driver: webdriver.Chrome) -> List[Dict]:
        lat, lng, place_id, description = _LOCATION.get(self._pincode[:3], _DEFAULT)

        # ── Step 1: Load homepage to seed cookies ─────────────────────────────
        self.log(f"  [Zepto] → {HOMEPAGE} (seeding session)")
        driver.get(HOMEPAGE)
        time.sleep(3)

        # ── Step 2: Inject location into localStorage ─────────────────────────
        location_payload = {
            "state": {
                "userPosition": {
                    "place_id": place_id,
                    "description": description,
                    "structured_formatting": {
                        "main_text": description.split(",")[0],
                        "secondary_text": ", ".join(description.split(",")[1:]).strip()
                    }
                },
                "userGpsCoords": {"latitude": lat, "longitude": lng},
                "userGpsCoordsUpdatedAt": int(datetime.now().timestamp() * 1000),
                "_hasHydrated": True
            },
            "version": 0
        }
        driver.execute_script(
            "localStorage.setItem('user-position', arguments[0])",
            json.dumps(location_payload)
        )
        self.log(f"  [Zepto] 📍 Location set: {description}")

        # ── Step 3: Load search page ──────────────────────────────────────────
        url = SEARCH_URL.format(query=query.replace(" ", "+"))
        self.log(f"  [Zepto] → {url}")
        driver.get(url)
        time.sleep(8)   # Zepto React hydration takes longer than most sites

        # Re-inject location after page load (Next.js might reset localStorage)
        driver.execute_script(
            "localStorage.setItem('user-position', arguments[0])",
            json.dumps(location_payload)
        )
        # Reload once more so React picks up the injected location
        driver.get(url)
        time.sleep(6)

        soup = BeautifulSoup(driver.page_source, "html.parser")
        results = self._parse(soup)

        if not results:
            self.log("  [Zepto] HTML parse got 0 — trying __NEXT_DATA__")
            nd = self._next_data(driver)
            if nd:
                results = self._walk_nd(nd)

        if results:
            self.log(f"  [Zepto] {len(results)} products parsed")
        else:
            self.log("  [Zepto] 0 products — location may not be serviceable")
        return results

    # ── HTML parser ───────────────────────────────────────────────────────────
    def _parse(self, soup: BeautifulSoup) -> List[Dict]:
        """
        Zepto renders product cards. Each card typically has:
          - A name element (h4, p, span with product name)
          - A price element with ₹
          - Optionally a weight/size text
        """
        results: List[Dict] = []
        seen: set = set()

        # Strategy A: find price elements and walk up to product card
        # NOTE: use get_text() not t.string — React nests spans inside price elements
        # so t.string is None even when the visible text contains ₹
        price_els = [
            t for t in soup.find_all(["span", "div", "p"])
            if not t.find(["span","div","p"])  # leaf-ish elements only
            and re.search(r"₹\s*\d+", t.get_text(strip=True))
        ]

        for pel in price_els[:60]:
            price_val = self._clean_price(pel.get_text(strip=True))
            if not price_val or price_val < 1:
                continue

            # Walk up to find name and optional MRP
            card = pel
            name = ""
            mrp  = 0.0
            for _ in range(12):
                card = card.parent
                if card is None:
                    break
                # Look for name in heading or data-testid or class-named element
                ne = (
                    card.find("h4") or card.find("h3") or card.find("h2") or
                    card.find(attrs={"data-testid": re.compile(r"name|title|product", re.I)}) or
                    card.find(attrs={"class": re.compile(r"name|title|product|item", re.I)})
                )
                if ne:
                    candidate = ne.get_text(strip=True)
                    if len(candidate) > 3 and not re.match(r"^₹", candidate):
                        name = candidate
                        break

                # Also check sibling price elements for MRP (usually > selling price)
                if not mrp:
                    all_prices = re.findall(r"₹\s*(\d+(?:\.\d+)?)", card.get_text())
                    all_p = [float(x) for x in all_prices if float(x) > 0]
                    if len(all_p) >= 2:
                        max_p = max(all_p)
                        if max_p > price_val:
                            mrp = max_p

            if name and price_val and name not in seen:
                seen.add(name)
                rec = self._build(name, price_val, mrp=mrp)

                # ── Product URL extraction ──────────────────────────────────
                # Strategy 1: look for a product-pattern <a> inside current card level
                product_url = ""
                if card is not None:
                    # Prefer links that look like Zepto product pages (/pn/ or /cn/)
                    a_tag = card.find("a", href=re.compile(r"/(pn|cn|pd)/"))
                    if not a_tag:
                        a_tag = card.find("a", href=True)
                    if a_tag:
                        href = a_tag.get("href", "")
                        if href and href.startswith("/") and len(href) > 3:
                            product_url = "https://www.zepto.com" + href

                # Strategy 2: walk UP — Zepto wraps product cards in <a> tags
                # Typical: <a href="/pn/atta/..."> <div class="product-card"> ... </a>
                if not product_url and card is not None:
                    node = card
                    for _ in range(6):
                        node = getattr(node, "parent", None)
                        if node is None:
                            break
                        if getattr(node, "name", "") == "a":
                            href = node.get("href", "")
                            if href and href.startswith("/") and len(href) > 3:
                                product_url = "https://www.zepto.com" + href
                                break
                        # Check for product-path <a> among node's children
                        a_tag = node.find("a", href=re.compile(r"/(pn|cn)/"))
                        if a_tag:
                            href = a_tag.get("href", "")
                            product_url = "https://www.zepto.com" + href
                            break

                rec["product_url"] = product_url
                results.append(rec)

        return results

    # ── __NEXT_DATA__ walker ──────────────────────────────────────────────────
    def _walk_nd(self, nd) -> List[Dict]:
        cands: list = []
        self._dig(nd, cands, 0)
        if not cands:
            return []
        out  = []
        seen = set()
        for item in max(cands, key=len)[:50]:
            name  = (item.get("name") or item.get("product_name") or
                     item.get("productName") or item.get("display_name") or "")
            price = (item.get("discountedSellingPrice") or
                     item.get("sellingPrice") or item.get("price") or
                     item.get("mrp") or item.get("selling_price"))
            mrp_raw = item.get("mrp") or item.get("market_price") or 0
            brand   = item.get("brand") or item.get("brandName") or ""
            price   = self._clean_price(str(price)) if price else None
            mrp     = self._clean_price(str(mrp_raw)) if mrp_raw else 0.0
            if name and price and str(name) not in seen:
                seen.add(str(name))
                rec = self._build(str(name), price, brand=str(brand), mrp=mrp or 0.0)
                # Try to extract product URL from __NEXT_DATA__
                url_key = (item.get("urlKey") or item.get("url_key") or
                           item.get("slug") or item.get("productUrl") or
                           item.get("product_url") or "")
                if url_key:
                    rec["product_url"] = (
                        "https://www.zepto.com" + url_key
                        if url_key.startswith("/") else url_key
                    )
                out.append(rec)
        return out

    def _dig(self, obj, found, depth):
        if depth > 14: return
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            k = set(obj[0].keys())
            if k & {"price", "mrp", "name", "productName", "product_name",
                    "sellingPrice", "discountedSellingPrice", "display_name"}:
                found.append(obj); return
        if isinstance(obj, dict):
            for v in obj.values(): self._dig(v, found, depth + 1)
        elif isinstance(obj, list):
            for i in obj: self._dig(i, found, depth + 1)
