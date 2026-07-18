"""
bigbasket.py
------------
BigBasket Selenium scraper.

BigBasket uses Next.js — product data is embedded in __NEXT_DATA__ on the
search page. We also try HTML card parsing as fallback.

Search URL: https://www.bigbasket.com/ps/?q={query}&nc=as
"""

import re
from typing import List, Dict, Optional

from selenium import webdriver
from bs4 import BeautifulSoup

from .base import BaseScraper

SEARCH_URL = "https://www.bigbasket.com/ps/?q={query}&nc=as"

# Strip ratings, review counts, standalone long numbers from product names
_NOISE = re.compile(
    r"\d+(\.\d+)?\s*(Ratings?|Reviews?|Stars?|out\s+of\s+\d)"
    r"|\s+\d{4,}"          # long numbers like "415156"
    r"|\(\d+\)",           # numbers in parens like "(150)"
    flags=re.I,
)
# Also strip everything from " X.Y Ratings" or " X Ratings" pattern
_RATING_TAIL = re.compile(r"\s+\d+(\.\d+)?\s+Ratings?.*$", flags=re.I)


class BigBasketScraper(BaseScraper):
    platform      = "BigBasket"
    delivery_mins = 30   # BigBasket Now ~30 min in major cities

    def _fetch(self, query: str, driver: webdriver.Chrome) -> List[Dict]:
        url = SEARCH_URL.format(query=query.replace(" ", "+"))
        self._get_page(driver, url,
                       wait_selector="[class*='SKUDeck'], li, [class*='product']",
                       timeout=20)

        # ── Strategy 1: __NEXT_DATA__ JSON ────────────────────────────────────
        nd = self._next_data(driver)
        if nd:
            prods = self._walk_nd(nd)
            if prods:
                self.log(f"  [BigBasket] {len(prods)} via __NEXT_DATA__")
                return prods

        # ── Strategy 2: HTML — walk up from ₹ price elements ─────────────────
        soup  = BeautifulSoup(driver.page_source, "html.parser")
        prods = self._parse_from_prices(soup)
        if prods:
            self.log(f"  [BigBasket] {len(prods)} via HTML price-walk")
            return prods

        self.log("  [BigBasket] 0 products")
        return []

    # ── __NEXT_DATA__ ──────────────────────────────────────────────────────────
    def _walk_nd(self, nd) -> List[Dict]:
        cands: list = []
        self._dig(nd, cands, 0)
        if not cands:
            return []
        out = []
        for item in max(cands, key=len)[:40]:
            rec = self._nd_item(item)
            if rec:
                out.append(rec)
        return out

    def _dig(self, obj, found, depth):
        if depth > 12: return
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            if set(obj[0]) & {"sp", "selling_price", "mrp", "desc", "product_name", "name"}:
                found.append(obj); return
        if isinstance(obj, dict):
            for v in obj.values(): self._dig(v, found, depth + 1)
        elif isinstance(obj, list):
            for i in obj: self._dig(i, found, depth + 1)

    def _nd_item(self, item: dict) -> Optional[Dict]:
        price = item.get("sp") or item.get("selling_price") or item.get("price")
        name  = item.get("product_name") or item.get("name") or ""
        bi    = item.get("brand") or {}
        brand = bi.get("name", "") if isinstance(bi, dict) else str(bi)
        desc  = item.get("desc") or item.get("description") or ""
        mrp_raw = item.get("mrp") or item.get("market_price") or item.get("original_price")

        # Product URL from url_key or absolute_url
        url_key = item.get("absolute_url") or item.get("url") or ""
        product_url = ("https://www.bigbasket.com" + url_key
                       if url_key and url_key.startswith("/") else url_key)

        price = self._clean_price(str(price)) if price else None
        mrp   = self._clean_price(str(mrp_raw)) if mrp_raw else 0.0
        if not price or not name:
            return None

        rec = self._build(str(name), price, brand=str(brand), description=str(desc),
                          mrp=mrp or 0.0)
        rec["product_url"] = product_url
        # Override size_label with the BigBasket pack field if present
        qty = item.get("w") or item.get("pack_desc") or ""
        if qty:
            rec["size_label"] = str(qty)[:30]
            # Re-parse quantity/unit from the pack descriptor for accurate ppu
            qs, ut, _ = self._extract_size(str(qty))
            rec["quantity"] = qs
            rec["unit"]     = ut
            # Recalculate ppu
            try:
                p  = float(price);  q = float(qs)
                u  = ut.lower()
                if u == "g":     rec["price_per_unit"] = round(p / q * 100, 2)
                elif u == "kg":  rec["price_per_unit"] = round(p / (q*1000) * 100, 2)
                elif u == "ml":  rec["price_per_unit"] = round(p / q * 100, 2)
                elif u == "l":   rec["price_per_unit"] = round(p / (q*1000) * 100, 2)
                elif u == "pcs": rec["price_per_unit"] = round(p / q, 2)
            except Exception:
                pass
        return rec

    # ── HTML price-walk ────────────────────────────────────────────────────────
    def _parse_from_prices(self, soup: BeautifulSoup) -> List[Dict]:
        """
        Find every element that contains a ₹ price, walk up the DOM
        to find the nearest product name in the same card.
        """
        results = []
        seen: set = set()

        price_els = [
            t for t in soup.find_all(["span", "div", "p", "strong"])
            if t.string and re.match(r"^\s*₹\s*\d", t.string)
        ]

        for pel in price_els[:50]:
            price_val = self._clean_price(pel.get_text(strip=True))
            if not price_val or price_val < 1:
                continue

            # Walk up DOM to find the nearest name heading
            card = pel
            name  = ""
            brand = ""
            for _ in range(8):
                card = card.parent
                if card is None:
                    break

                # Brand: look for span/div with class matching 'brand'
                if not brand:
                    be = card.find(class_=re.compile(r"brand", re.I))
                    if be:
                        brand = be.get_text(strip=True)[:40]

                # Name: look for a heading or named element
                ne = (card.find("h3") or card.find("h2") or
                      card.find(class_=re.compile(r"name|Name|title|Title|prod", re.I)))
                if ne:
                    raw  = ne.get_text(" ", strip=True)
                    name = self._clean_bb_name(raw, brand)
                    if len(name) > 4:
                        break

            if not name or price_val < 1:
                continue

            key = f"{name}_{price_val}"
            if key not in seen:
                seen.add(key)
                rec = self._build(name, price_val, brand=brand)
                # Try to extract product URL from <a> inside or above card
                product_url = ""
                if card is not None:
                    a_tag = card.find("a", href=re.compile(r"^/pd/"))
                    if not a_tag:
                        a_tag = card.find("a", href=True)
                    if a_tag:
                        href = a_tag.get("href", "")
                        if href.startswith("/"):
                            product_url = "https://www.bigbasket.com" + href
                # Walk up if not found inside
                if not product_url and card is not None:
                    node = card
                    for _ in range(4):
                        node = getattr(node, "parent", None)
                        if node is None:
                            break
                        if getattr(node, "name", "") == "a":
                            href = node.get("href", "")
                            if href and href.startswith("/"):
                                product_url = "https://www.bigbasket.com" + href
                                break
                rec["product_url"] = product_url
                results.append(rec)

        return results

    @staticmethod
    def _clean_bb_name(raw: str, brand: str) -> str:
        """Remove rating noise and brand prefix from a BigBasket product name."""
        # Strip at first occurrence of "N.N Ratings" or "N Ratings"
        name = re.sub(r"\s*\d+(\.\d+)?\s*Ratings?.*$", "", raw, flags=re.I)
        # Remove leftover trailing decimal/integer (e.g. trailing " 4.1" or " 4")
        name = re.sub(r"\s+\d+(\.\d+)?\s*$", "", name)
        # Remove long standalone numbers > 4 digits
        name = re.sub(r"\s+\d{5,}", "", name)
        # Remove brand prefix if merged ("AmulGold..." → "Gold...")
        if brand and name.lower().startswith(brand.lower()):
            name = name[len(brand):].strip()
        return " ".join(name.split()).strip()
