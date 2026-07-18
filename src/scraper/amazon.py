"""
amazon.py
---------
Amazon.in grocery Selenium scraper.

After Selenium loads the page we parse with BeautifulSoup.
Amazon search result card structure (2024):
  <div data-component-type="s-search-result">
    <h2 class="..."><a href="..."><span>Full Product Title Here</span></a></h2>
    <span class="a-price">
      <span class="a-offscreen">₹65.00</span>
      <span aria-hidden="true">
        <span class="a-price-whole">65</span>
      </span>
    </span>
  </div>
"""

import re
from typing import List, Dict, Optional

from selenium import webdriver
from bs4 import BeautifulSoup, Tag

from .base import BaseScraper

SEARCH_URL = "https://www.amazon.in/s?k={query}&i=grocery"


class AmazonScraper(BaseScraper):
    platform      = "Amazon Fresh"
    delivery_mins = 120  # Amazon Fresh same-day ~2 hours

    def _fetch(self, query: str, driver: webdriver.Chrome) -> List[Dict]:
        url = SEARCH_URL.format(query=query.replace(" ", "+"))
        self._get_page(
            driver, url,
            wait_selector='[data-component-type="s-search-result"]',
            timeout=20,
        )

        soup  = BeautifulSoup(driver.page_source, "html.parser")
        cards = soup.select('[data-component-type="s-search-result"]')
        self.log(f"  [Amazon] {len(cards)} result cards")

        results = []
        seen: set = set()
        for card in cards[:35]:
            rec = self._parse(card)
            if rec and rec["product_name"] not in seen:
                seen.add(rec["product_name"])
                results.append(rec)
        return results

    def _parse(self, card: Tag) -> Optional[Dict]:
        # ── Title: get the longest span text inside h2 ────────────────────────
        name = ""
        h2 = card.find("h2")
        if h2:
            # Collect all span texts inside h2, pick the longest one
            spans = h2.find_all("span")
            candidates = [s.get_text(strip=True) for s in spans if s.get_text(strip=True)]
            if candidates:
                name = max(candidates, key=len)
        if not name or len(name) < 4:
            return None

        # ── Price ─────────────────────────────────────────────────────────────
        price = None
        mrp   = 0.0

        # Amazon renders .a-price containers in DOM order:
        #   1st container = selling price
        #   2nd container = MRP / strikethrough (class includes "a-text-strike" or
        #                   aria-label contains "M.R.P" / "was")
        # IMPORTANT: do NOT use min() — it accidentally picks up per-unit price
        # elements (e.g. "₹7.72/100 g" rendered as a separate .a-price).
        price_containers = card.select(".a-price")
        prices_found = []
        for pc in price_containers:
            offscreen = pc.select_one(".a-offscreen")
            if offscreen:
                p = self._clean_price(offscreen.get_text(strip=True))
                if p and p > 1:
                    prices_found.append(p)

        if prices_found:
            # First price in DOM = selling price (Amazon always renders it first)
            price = prices_found[0]
            # MRP = highest price found (if greater than selling price)
            max_p = max(prices_found)
            mrp   = max_p if max_p > price else 0.0

            # ── Sanity check ────────────────────────────────────────────────
            # If price is < 5 % of MRP, we likely grabbed a per-unit sub-price.
            # Walk forward in the list to find a sensible selling price.
            if mrp and price < mrp * 0.05:
                reasonable = [p for p in prices_found if p >= mrp * 0.05]
                price = reasonable[0] if reasonable else mrp
        else:
            # Fallback: whole.fraction spans
            whole = card.select_one(".a-price-whole")
            if whole:
                w = whole.get_text(strip=True).replace(",", "").rstrip(".")
                frac_el = card.select_one(".a-price-fraction")
                f = frac_el.get_text(strip=True) if frac_el else "00"
                price = self._clean_price(f"{w}.{f}")

        if not price:
            return None

        # ── Product URL ───────────────────────────────────────────────────────
        product_url = ""
        a_tag = card.select_one("h2 a[href]")
        if a_tag:
            href = a_tag.get("href", "")
            product_url = ("https://www.amazon.in" + href) if href.startswith("/") else href

        # ── Brand ─────────────────────────────────────────────────────────────
        words = name.split()
        brand = words[0] if (words and len(words[0]) > 1 and
                             not words[0][0].isdigit()) else ""

        # ── Description: product feature bullets if present ───────────────────
        desc = ""
        bullets = card.select(".a-list-item, .a-size-base.a-color-base")
        if bullets:
            parts = [b.get_text(strip=True) for b in bullets[:2]
                     if len(b.get_text(strip=True)) > 5]
            desc = " | ".join(parts)[:200]

        rec = self._build(name, price, brand=brand, description=desc, mrp=mrp)
        rec["product_url"] = product_url
        return rec
