"""
manager.py
----------
Orchestrates all Selenium scrapers with ONE shared Chrome driver.

Active platforms (real-time data confirmed):
  1. Amazon Fresh   — BeautifulSoup card parse
  2. Blinkit        — Selenium + location cookie
  3. BigBasket      — __NEXT_DATA__ JSON extraction
  4. Zepto          — localStorage location injection

Commented out (future work — files kept intact):
  5. Flipkart       — CSS class names change too frequently; re-enable when stable
  6. Swiggy Instamart — requires logged-in Swiggy session; blocked by AWS WAF

All scrapers:
  - Use real headless Chrome (Selenium)
  - If a platform fails/is blocked → logs reason → returns [] → pipeline continues
  - One Chrome instance shared across all scrapers (faster startup)
"""

import time
from typing import List, Dict, Callable

from .base       import build_chrome_driver
from .amazon     import AmazonScraper
from .blinkit    import BlinkitScraper
from .bigbasket  import BigBasketScraper
from .zepto      import ZeptoScraper
# from .flipkart   import FlipkartScraper   # TODO: re-enable when Flipkart CSS stabilises
# from .instamart  import InstamartScraper  # TODO: re-enable with authenticated Swiggy session
from .delivery   import stamp_delivery, get_city

SCRAPER_CLASSES = [
    AmazonScraper,       # 1 — ✅ active
    BlinkitScraper,      # 2 — ✅ active
    BigBasketScraper,    # 3 — ✅ active
    ZeptoScraper,        # 4 — ✅ active
    # FlipkartScraper,   # 5 — ⏳ future: CSS class names change frequently
    # InstamartScraper,  # 6 — ⏳ future: needs Swiggy authenticated session
]


class ScraperManager:
    def __init__(self, log_callback: Callable):
        self.log      = log_callback
        self.scrapers = [cls(log_callback) for cls in SCRAPER_CLASSES]

    def scrape_all(self, query: str, pincode: str,
                   screenshot_dir: str = "",
                   progress_cb=None) -> List[Dict]:
        """
        Scrape all active platforms.

        Args:
            screenshot_dir : folder to save browser screenshots (empty = skip)
            progress_cb    : callable(platform, n_results, elapsed_s) called
                             after each platform finishes — used to update UI
        """
        self.log("=" * 58)
        self.log("PHASE 1 — SCRAPING  (Selenium / headless Chrome)")
        self.log(f"Query    : {query}")
        self.log(f"Pincode  : {pincode}")
        self.log(f"Platforms: {', '.join(s.platform for s in self.scrapers)}")
        city = get_city(pincode)
        self.log(f"City     : {city or 'Unknown — using tier-2 estimates'}")
        self.log("=" * 58)

        driver      = None
        all_results: List[Dict] = []
        summary:     List[str]  = []

        try:
            driver = build_chrome_driver(self.log)

            for scraper in self.scrapers:
                t0      = time.time()
                results = scraper.scrape(query, driver, pincode=pincode,
                                         screenshot_dir=screenshot_dir)
                elapsed = round(time.time() - t0, 2)

                # Stamp pincode on each record
                for r in results:
                    r["pincode"] = pincode

                live  = sum(1 for r in results if r.get("source") == "LIVE")
                label = f"{live} live" if results else "blocked / no data"
                summary.append(
                    f"  {scraper.platform:<24}: {len(results):>3} products  "
                    f"[{label}]  {elapsed}s"
                )
                all_results.extend(results)

                # Notify app.py so it can update the live progress card
                if progress_cb:
                    try:
                        progress_cb(scraper.platform, len(results), elapsed)
                    except Exception:
                        pass

        except Exception as e:
            self.log(f"\n  [Manager] ❌ Browser error: {e}")
        finally:
            if driver:
                try:
                    driver.quit()
                    self.log("\n  [Chrome] Browser closed")
                except Exception:
                    pass

        self.log("\n" + "─" * 58)
        self.log("SCRAPING SUMMARY")
        for s in summary:
            self.log(s)
        # Stamp pincode-based delivery times on every record
        all_results = stamp_delivery(all_results, pincode)

        city = get_city(pincode)
        self.log(f"\n  Total products found: {len(all_results)}")
        self.log(f"  Delivery times      : based on pincode {pincode} ({city or 'tier-2 city'})")
        self.log("─" * 58)

        return all_results
