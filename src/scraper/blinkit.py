"""
blinkit.py
----------
Blinkit Selenium scraper.

HTML structure (from live inspection):
  <div class="tw-w-full tw-px-3">           ← outer card (has delivery "9 mins")
    <div class="tw-flex tw-w-full tw-flex-col">  ← inner card
      [product name + size text]
      <div class="tw-flex tw-items-center tw-justify-between">
        ₹[price]   ₹[MRP]   ADD
      </div>
    </div>
  </div>

Strategy: find every price-containing element, walk up to the
  "tw-flex tw-w-full tw-flex-col" container, extract product name
  as everything in the text before the first ₹ sign.
"""

import re
from typing import List, Dict, Optional

from selenium import webdriver
from bs4 import BeautifulSoup

from .base import BaseScraper

SEARCH_URL  = "https://blinkit.com/s/?q={query}"


class BlinkitScraper(BaseScraper):
    platform      = "Blinkit"
    delivery_mins = 10

    def _fetch(self, query: str, driver: webdriver.Chrome) -> List[Dict]:
        url  = SEARCH_URL.format(query=query.replace(" ", "+"))
        self._get_page(driver, url,
                       wait_selector="div[class*='tw-flex'][class*='tw-w-full']",
                       timeout=18)

        soup    = BeautifulSoup(driver.page_source, "html.parser")
        results = self._parse(soup)

        if results:
            self.log(f"  [Blinkit] {len(results)} products parsed")
        else:
            self.log("  [Blinkit] 0 products — location wall or no results")
        return results

    def _parse(self, soup: BeautifulSoup) -> List[Dict]:
        results: List[Dict] = []
        seen: set = set()

        # ── find product cards ──────────────────────────────────────────────
        # Each card is a <div class="tw-flex tw-w-full tw-flex-col">
        # that contains product name text + price elements
        cards = soup.find_all("div", class_=lambda c: c and
                              "tw-flex" in c and "tw-w-full" in c and "tw-flex-col" in c)

        for card in cards:
            rec = self._parse_card(card)
            if rec and rec["product_name"] not in seen:
                seen.add(rec["product_name"])
                results.append(rec)

        # ── fallback: walk up from raw ₹ elements ───────────────────────────
        if not results:
            results = self._fallback_price_walk(soup)

        return results

    def _parse_card(self, card) -> Optional[Dict]:
        full_text = card.get_text(" ", strip=True)
        if "₹" not in full_text:
            return None

        # Product name = everything before the first ₹
        parts = full_text.split("₹")
        raw_name = parts[0].strip()

        # Remove "X mins" delivery prefix if present
        delivery_match = re.match(r"^(\d+)\s*mins?\s+(.*)", raw_name, re.I)
        if delivery_match:
            raw_name = delivery_match.group(2).strip()

        # Clean up trailing ADD / button text
        raw_name = re.sub(r"\s*(ADD|add)\s*$", "", raw_name).strip()
        if not raw_name or len(raw_name) < 3:
            return None

        # Extract all ₹ prices from the card
        # Blinkit layout: ₹[selling_price]  ₹[MRP]  ADD
        prices = re.findall(r"₹\s*(\d+(?:\.\d+)?)", full_text)
        if not prices:
            return None
        price = self._clean_price(prices[0])
        if not price:
            return None
        # Second price (if larger) is the MRP
        mrp = 0.0
        if len(prices) >= 2:
            m = self._clean_price(prices[1])
            if m and m > price:
                mrp = m

        # Extract delivery time from parent or sibling text
        dm = self.delivery_mins
        parent = card.parent
        if parent:
            parent_text = parent.get_text(" ", strip=True)
            dm_match = re.search(r"(\d+)\s*mins?", parent_text, re.I)
            if dm_match:
                dm = int(dm_match.group(1))

        rec = self._build(raw_name, price, mrp=mrp)
        rec["delivery_mins"] = dm

        # ── Product URL extraction ──────────────────────────────────────────
        # Strategy 1: look for <a> INSIDE the card (e.g., product image link)
        product_url = ""
        a_inner = card.find("a", href=True)
        if a_inner:
            href = a_inner.get("href", "")
            if href.startswith("/") and len(href) > 3:
                product_url = "https://blinkit.com" + href

        # Strategy 2: walk UP ancestors — Blinkit wraps the entire card in <a>
        # Typical structure: <a href="/prn/product/500-g/prid/12345"> <div.tw-w-full> <div.tw-flex...>
        if not product_url:
            node = card
            for _ in range(6):
                node = getattr(node, "parent", None)
                if node is None:
                    break
                if getattr(node, "name", "") == "a":
                    href = node.get("href", "")
                    if href and href.startswith("/") and len(href) > 3:
                        product_url = "https://blinkit.com" + href
                        break
                # Also check for a single product-pattern <a> inside this ancestor
                # (e.g., /prn/ or /pn/ paths)
                a_tag = node.find("a", href=re.compile(r"^/(prn|pn)/"))
                if a_tag:
                    href = a_tag.get("href", "")
                    product_url = "https://blinkit.com" + href
                    break

        rec["product_url"] = product_url
        return rec

    def _fallback_price_walk(self, soup: BeautifulSoup) -> List[Dict]:
        """Walk up from ₹ elements when card detection fails."""
        results, seen = [], set()
        price_els = [t for t in soup.find_all(["span", "div"])
                     if t.string and re.match(r"^\s*₹\s*\d", t.string)]
        for pel in price_els[:40]:
            price_val = self._clean_price(pel.get_text(strip=True))
            if not price_val:
                continue
            card, name = pel, ""
            for _ in range(5):
                card = card.parent
                if card is None:
                    break
                text = card.get_text(" ", strip=True)
                before_price = text.split("₹")[0].strip()
                before_price = re.sub(r"^\d+\s*mins?\s*", "", before_price, flags=re.I)
                before_price = re.sub(r"\s*(ADD|add)\s*$", "", before_price).strip()
                if len(before_price) > 4:
                    name = before_price
                    break
            if name and price_val and name not in seen:
                seen.add(name)
                results.append(self._build(name, price_val))
        return results
