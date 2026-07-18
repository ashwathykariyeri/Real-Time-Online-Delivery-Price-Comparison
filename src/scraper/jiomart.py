"""
jiomart.py
----------
JioMart Selenium scraper.

JioMart search page: https://www.jiomart.com/search/{query}
Products render as React components. We wait for the product cards
and parse names + prices from the rendered HTML.
Also tries __NEXT_DATA__ if available.
"""

import re
from typing import List, Dict

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .base import BaseScraper

SEARCH_URL = "https://www.jiomart.com/search/{query}"


class JioMartScraper(BaseScraper):
    platform      = "JioMart"
    delivery_mins = 45   # JioMart Express ~45 min

    def _fetch(self, query: str, driver: webdriver.Chrome) -> List[Dict]:
        url = SEARCH_URL.format(query=query.replace(" ", "%20"))
        soup = self._get_page(
            driver, url,
            wait_selector="[class*='product'], [class*='card'], [class*='item']",
            timeout=20,
        )

        # ── Strategy 1: __NEXT_DATA__ JSON ────────────────────────────────────
        nd = self._next_data(driver)
        if nd:
            results = self._parse_next_data(nd)
            if results:
                self.log(f"  [JioMart] Parsed {len(results)} products via __NEXT_DATA__")
                return results

        # ── Strategy 2: HTML product cards ────────────────────────────────────
        results = self._parse_html(soup)
        if results:
            self.log(f"  [JioMart] Parsed {len(results)} products via HTML")
            return results

        self.log("  [JioMart] 0 products found")
        return []

    def _parse_next_data(self, nd: dict) -> List[Dict]:
        candidates: list = []
        self._find_product_lists(nd, candidates, 0)
        if not candidates:
            return []
        best = max(candidates, key=len)
        results = []
        for item in best[:40]:
            name  = (item.get("name") or item.get("product_name") or
                     item.get("title") or "")
            price = (item.get("price") or item.get("sp") or
                     item.get("selling_price") or item.get("discounted_price"))
            brand = item.get("brand") or ""
            desc  = item.get("description") or item.get("short_description") or ""

            price = self._clean_price(str(price)) if price else None
            if name and price:
                results.append(self._build(str(name), price,
                                           brand=str(brand), description=str(desc)))
        return results

    def _find_product_lists(self, obj, found: list, depth: int):
        if depth > 12:
            return
        if isinstance(obj, list) and len(obj) > 0 and isinstance(obj[0], dict):
            keys = set(obj[0].keys())
            if keys & {"price", "sp", "selling_price", "name", "product_name", "title"}:
                found.append(obj)
                return
        if isinstance(obj, dict):
            for v in obj.values():
                self._find_product_lists(v, found, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                self._find_product_lists(item, found, depth + 1)

    def _parse_html(self, soup) -> List[Dict]:
        results = []
        seen: set = set()

        # JioMart price elements often have ₹ or class names like 'price'
        price_els = [
            t for t in soup.find_all(["span", "div", "p", "strong"])
            if t.string and re.search(r"₹\s*\d+", t.string)
        ]

        for pel in price_els[:40]:
            price_val = self._clean_price(pel.get_text(strip=True))
            if not price_val:
                continue
            card = pel
            name = ""
            brand = ""
            for _ in range(8):
                card = card.parent
                if card is None:
                    break
                # Try to find name
                name_el = (card.find("p", class_=re.compile(r"name|title|desc", re.I)) or
                           card.find("h3") or card.find("h2") or
                           card.find("a", title=True))
                if name_el:
                    name = name_el.get_text(strip=True)
                    if len(name) > 4:
                        break
            if name and price_val and name not in seen:
                seen.add(name)
                results.append(self._build(name, price_val, brand=brand))

        return results
