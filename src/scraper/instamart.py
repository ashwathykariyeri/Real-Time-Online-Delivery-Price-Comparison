"""
instamart.py
------------
Swiggy Instamart Selenium scraper.

Diagnostic findings:
  - Location stored in cookie: userLocation = {"lat":"...","lng":"...","address":"..."}
  - Strategy: delete old cookie, inject Bangalore coords, load search page,
    wait for React to fetch products dynamically.
  - Products load via client-side API calls after page hydration.
"""

import re
import json
import time
import urllib.parse
from typing import List, Dict

from selenium import webdriver
from bs4 import BeautifulSoup

from .base import BaseScraper

HOMEPAGE   = "https://www.swiggy.com/"
SEARCH_URL = "https://www.swiggy.com/instamart/search?query={query}"

_LOCATION = {
    "560": ("12.9716", "77.5946", "Bangalore"),
    "562": ("12.9716", "77.5946", "Bangalore"),
    "110": ("28.6139", "77.2090", "New Delhi"),
    "122": ("28.4595", "77.0266", "Gurugram"),
    "201": ("28.5355", "77.3910", "Noida"),
    "400": ("19.0760", "72.8777", "Mumbai"),
    "401": ("19.0760", "72.8777", "Mumbai"),
    "411": ("18.5204", "73.8567", "Pune"),
    "500": ("17.3850", "78.4867", "Hyderabad"),
    "600": ("13.0827", "80.2707", "Chennai"),
    "700": ("22.5726", "88.3639", "Kolkata"),
    "380": ("23.0225", "72.5714", "Ahmedabad"),
}
_DEFAULT = ("12.9716", "77.5946", "Bangalore")


class InstamartScraper(BaseScraper):
    platform      = "Swiggy Instamart"
    delivery_mins = 18

    def _fetch(self, query: str, driver: webdriver.Chrome) -> List[Dict]:
        lat, lng, city = _LOCATION.get(self._pincode[:3], _DEFAULT)

        # ── Step 1: seed session on Swiggy homepage ───────────────────────────
        self.log(f"  [Instamart] → {HOMEPAGE} (seeding session)")
        driver.get(HOMEPAGE)
        time.sleep(4)

        # ── Step 2: inject Bangalore into userLocation cookie ─────────────────
        driver.delete_cookie("userLocation")
        new_loc = urllib.parse.quote(json.dumps({
            "lat": lat, "lng": lng,
            "address": city, "area": city,
            "showUserDefaultAddressHint": False
        }))
        driver.add_cookie({
            "name": "userLocation", "value": new_loc,
            "domain": ".swiggy.com", "path": "/"
        })
        self.log(f"  [Instamart] 📍 Location set: {city}")

        # ── Step 3: load search page and wait for dynamic products ────────────
        url = SEARCH_URL.format(query=query.replace(" ", "+"))
        self.log(f"  [Instamart] → {url}")
        driver.get(url)
        time.sleep(3)
        driver.refresh()
        time.sleep(10)   # Swiggy loads products via client-side API calls

        soup    = BeautifulSoup(driver.page_source, "html.parser")
        results = self._parse(soup)

        if results:
            self.log(f"  [Instamart] {len(results)} products parsed")
        else:
            self.log("  [Instamart] 0 products — may need login for this area")
        return results

    # ── HTML parser ───────────────────────────────────────────────────────────
    def _parse(self, soup: BeautifulSoup) -> List[Dict]:
        results: List[Dict] = []
        seen: set = set()

        price_els = [
            t for t in soup.find_all(["span", "div", "p"])
            if t.string and re.search(r"₹\s*\d+", t.string)
        ]

        for pel in price_els[:60]:
            price_val = self._clean_price(pel.get_text(strip=True))
            if not price_val or price_val < 1:
                continue

            card, name, mrp = pel, "", 0.0
            for _ in range(10):
                card = card.parent
                if card is None:
                    break
                ne = (
                    card.find("h4") or card.find("h3") or card.find("h2") or
                    card.find(attrs={"class": re.compile(r"name|title|product", re.I)})
                )
                if ne:
                    candidate = ne.get_text(strip=True)
                    if len(candidate) > 3:
                        name = candidate
                        break
                if not mrp:
                    all_p = [float(x) for x in re.findall(r"₹\s*(\d+(?:\.\d+)?)", card.get_text()) if float(x) > 0]
                    if len(all_p) >= 2 and max(all_p) > price_val:
                        mrp = max(all_p)

            if name and price_val and name not in seen:
                seen.add(name)
                results.append(self._build(name, price_val, mrp=mrp))

        return results
