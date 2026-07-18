"""
flipkart.py
-----------
Flipkart Grocery Selenium scraper.
URL: https://www.flipkart.com/search?q={query}&sid=g07
No login or location needed — products are publicly visible.
"""

import re
from typing import List, Dict, Optional

from selenium import webdriver
from bs4 import BeautifulSoup

from .base import BaseScraper

SEARCH_URL = "https://www.flipkart.com/search?q={query}&sid=g07"


class FlipkartScraper(BaseScraper):
    platform      = "Flipkart"
    delivery_mins = 120   # Flipkart grocery ~2 hrs (next-day for most)

    def _fetch(self, query: str, driver: webdriver.Chrome) -> List[Dict]:
        url  = SEARCH_URL.format(query=query.replace(" ", "+"))
        soup = self._get_page(driver, url,
                              wait_selector="div[data-id], [class*='_1AtVbE'], [class*='_2kHMtA']",
                              timeout=18)

        results = self._parse(soup)
        if results:
            self.log(f"  [Flipkart] {len(results)} products parsed")
        else:
            self.log("  [Flipkart] 0 products")
        return results

    def _parse(self, soup: BeautifulSoup) -> List[Dict]:
        results: List[Dict] = []
        seen: set = set()

        # Flipkart encodes prices in ₹ text inside spans
        price_els = [
            t for t in soup.find_all(["div", "span"])
            if t.string and re.search(r"₹\s*\d+", t.string)
        ]

        for pel in price_els[:60]:
            price_val = self._clean_price(pel.get_text(strip=True))
            if not price_val or price_val < 1:
                continue

            card  = pel
            name  = ""
            mrp   = 0.0
            for _ in range(10):
                card = card.parent
                if card is None:
                    break

                # Flipkart product names are usually in <a title="..."> or div with class _4rR01T / IRpwTa
                ne = (
                    card.find("a",    title=True) or
                    card.find("div",  class_=re.compile(r"_4rR01T|IRpwTa|_2WkVRV|KzDlHZ|wjcEIp", re.I)) or
                    card.find("span", class_=re.compile(r"_4rR01T|IRpwTa|_2WkVRV", re.I)) or
                    card.find("a",    class_=re.compile(r"s1Q9rs|IRpwTa", re.I))
                )
                if ne:
                    candidate = ne.get("title") or ne.get_text(strip=True)
                    if candidate and len(candidate) > 4:
                        name = candidate
                        break

                # MRP — look for strikethrough price (class _3I9_wc or _3Ay6Sb)
                if not mrp:
                    mrp_el = card.find(class_=re.compile(r"_3I9_wc|_3Ay6Sb|dattD_", re.I))
                    if mrp_el:
                        m = self._clean_price(mrp_el.get_text(strip=True))
                        if m and m > price_val:
                            mrp = m

            if name and price_val and name not in seen:
                seen.add(name)
                results.append(self._build(name, price_val, mrp=mrp))

        return results
