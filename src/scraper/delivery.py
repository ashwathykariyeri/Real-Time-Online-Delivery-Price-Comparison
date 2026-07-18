"""
delivery.py
-----------
Pincode → delivery time estimates per platform.

These are based on each platform's published/typical SLAs:
  Blinkit / Zepto    — 10 min  (metro only, ~8-15 min)
  Swiggy Instamart   — 15 min  (metro) / 30 min (tier-2)
  BigBasket Now      — 30 min  (metro) / 60 min (tier-2)
  JioMart Express    — 45 min  (metro) / 90 min (tier-2)
  Amazon Fresh       — 2 hrs   (metro) / same-day only if available

For pincodes not in any serviced city, platforms are marked "Not available".
"""

from typing import Dict, Optional

# ── Metro city prefix map ─────────────────────────────────────────────────────
# key = first 3 digits of pincode → (city, {platform: mins})
CITY_DELIVERY: Dict[str, tuple] = {
    # Mumbai
    "400": ("Mumbai",    {"Blinkit": 10, "Zepto": 10, "Swiggy Instamart": 15,
                          "BigBasket": 25, "JioMart": 45, "Amazon Fresh": 120}),
    "401": ("Mumbai",    {"Blinkit": 12, "Zepto": 12, "Swiggy Instamart": 20,
                          "BigBasket": 30, "JioMart": 50, "Amazon Fresh": 120}),
    # Delhi / NCR
    "110": ("Delhi",     {"Blinkit": 10, "Zepto": 10, "Swiggy Instamart": 15,
                          "BigBasket": 25, "JioMart": 40, "Amazon Fresh": 120}),
    "122": ("Gurugram",  {"Blinkit": 10, "Zepto": 10, "Swiggy Instamart": 18,
                          "BigBasket": 30, "JioMart": 45, "Amazon Fresh": 120}),
    "201": ("Noida",     {"Blinkit": 10, "Zepto": 10, "Swiggy Instamart": 18,
                          "BigBasket": 30, "JioMart": 45, "Amazon Fresh": 120}),
    # Bangalore
    "560": ("Bangalore", {"Blinkit": 10, "Zepto": 10, "Swiggy Instamart": 15,
                          "BigBasket": 20, "JioMart": 45, "Amazon Fresh": 120}),
    "562": ("Bangalore", {"Blinkit": 12, "Zepto": 12, "Swiggy Instamart": 20,
                          "BigBasket": 30, "JioMart": 50, "Amazon Fresh": 120}),
    # Chennai
    "600": ("Chennai",   {"Blinkit": 12, "Zepto": 12, "Swiggy Instamart": 18,
                          "BigBasket": 30, "JioMart": 50, "Amazon Fresh": 120}),
    # Hyderabad
    "500": ("Hyderabad", {"Blinkit": 10, "Zepto": 10, "Swiggy Instamart": 15,
                          "BigBasket": 25, "JioMart": 45, "Amazon Fresh": 120}),
    # Kolkata
    "700": ("Kolkata",   {"Blinkit": 12, "Zepto": 15, "Swiggy Instamart": 20,
                          "BigBasket": 30, "JioMart": 60, "Amazon Fresh": 180}),
    # Pune
    "411": ("Pune",      {"Blinkit": 12, "Zepto": 12, "Swiggy Instamart": 18,
                          "BigBasket": 30, "JioMart": 50, "Amazon Fresh": 120}),
    # Ahmedabad
    "380": ("Ahmedabad", {"Blinkit": 12, "Zepto": 15, "Swiggy Instamart": 20,
                          "BigBasket": 35, "JioMart": 60, "Amazon Fresh": 180}),
    # Jaipur
    "302": ("Jaipur",    {"Blinkit": 15, "Zepto": 15, "Swiggy Instamart": 25,
                          "BigBasket": 40, "JioMart": 60, "Amazon Fresh": 180}),
    # Lucknow
    "226": ("Lucknow",   {"Blinkit": 15, "Zepto": 15, "Swiggy Instamart": 25,
                          "BigBasket": 45, "JioMart": 60, "Amazon Fresh": 240}),
    # Chandigarh
    "160": ("Chandigarh",{"Blinkit": 15, "Zepto": 15, "Swiggy Instamart": 25,
                          "BigBasket": 40, "JioMart": 60, "Amazon Fresh": 180}),
    # Indore
    "452": ("Indore",    {"Blinkit": 15, "Zepto": 20, "Swiggy Instamart": 25,
                          "BigBasket": 45, "JioMart": 60, "Amazon Fresh": 240}),
}

# Tier-2 / unknown fallback
_TIER2 = {
    "Blinkit": 20, "Zepto": 20, "Swiggy Instamart": 30,
    "BigBasket": 60, "JioMart": 90, "Amazon Fresh": 240,
}


def get_city(pincode: str) -> Optional[str]:
    """Return city name for a pincode, or None if unknown."""
    prefix = pincode[:3]
    if prefix in CITY_DELIVERY:
        return CITY_DELIVERY[prefix][0]
    return None


def delivery_mins(pincode: str, platform: str) -> int:
    """Return estimated delivery minutes for a platform at the given pincode."""
    prefix = pincode[:3]
    if prefix in CITY_DELIVERY:
        city_map = CITY_DELIVERY[prefix][1]
        return city_map.get(platform, _TIER2.get(platform, 60))
    return _TIER2.get(platform, 60)


def stamp_delivery(products: list, pincode: str) -> list:
    """
    Set delivery_mins on every product record using pincode-based lookup.
    Called by ScraperManager after all scrapers finish.
    """
    for p in products:
        plat = p.get("platform", "")
        p["delivery_mins"] = delivery_mins(pincode, plat)
    return products
