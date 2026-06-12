"""
app.py  —  Real-Time Indian Grocery Price Comparison
Run: streamlit run app.py
"""

import sys, os, json, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SCREENSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except: pass

import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="Grocery Price Compare",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="collapsed",
)

from src.scraper          import ScraperManager
from src.scraper.delivery import get_city
from src.pipeline         import KafkaPipeline, SparkProcessor
from src.database         import Database

# ── session state ─────────────────────────────────────────────────────────────
_defaults = {
    "results": [], "raw_data": [], "timings": {},
    "logs": [], "last_q": "", "last_pin": "", "searched": False,
    "kafka_meta": {}, "platform_summary": {},
    "screenshot_dir": SCREENSHOT_DIR,
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── header ────────────────────────────────────────────────────────────────────
st.title("🛒 Real-Time Indian Grocery Price Comparison")
st.caption(
    "Selenium → Apache Kafka → Apache Spark / Pandas → SQLite → Streamlit  |  "
    "Live Platforms: Amazon Fresh · Blinkit · BigBasket · Zepto"
)

# ── input row ─────────────────────────────────────────────────────────────────
c1, c2, c3 = st.columns([2, 5, 1])
with c1:
    pincode = st.text_input("📍 Pincode", value="560001", max_chars=6)
    city = get_city(pincode.strip()) if pincode.strip().isdigit() else None
    if city:
        st.caption(f"📌 {city}")
with c2:
    query = st.text_input("🛍️ Product Name", value="",
                           placeholder="e.g.  eggs  |  Amul Milk  |  Maggi Noodles")
with c3:
    st.markdown("<br>", unsafe_allow_html=True)
    go = st.button("🔍 Search", use_container_width=True, type="primary")

st.markdown("---")

# ── search handler ────────────────────────────────────────────────────────────
if go:
    q   = query.strip()
    pin = pincode.strip()
    if not q:
        st.warning("⚠️  Enter a product name."); st.stop()
    if not (pin.isdigit() and len(pin) == 6):
        st.warning("⚠️  Enter a valid 6-digit pincode."); st.stop()

    # reset state
    st.session_state.update(results=[], raw_data=[], timings={},
                            logs=[], last_q=q, last_pin=pin, searched=True)

    # ── Live Operations Terminal ───────────────────────────────────────────────
    term_exp = st.expander("📡 Live Operations Terminal", expanded=True)
    term_box = term_exp.empty()

    def log(msg: str):
        st.session_state.logs.append(msg)
        term_box.code("\n".join(st.session_state.logs[-40:]), language="")

    log(f"▶  Query: '{q}'   Pincode: {pin}   City: {get_city(pin) or 'unknown'}")
    log("=" * 62)

    # ── Phase 1 Progress Cards ─────────────────────────────────────────────────
    st.markdown("**🌐 Phase 1 — Live Scraping Progress (Selenium)**")
    ACTIVE_PLATFORMS = ["Amazon Fresh", "Blinkit", "BigBasket", "Zepto"]
    prog_cols = st.columns(4)
    prog_slots = {}
    for i, plat in enumerate(ACTIVE_PLATFORMS):
        with prog_cols[i]:
            prog_slots[plat] = st.empty()
            prog_slots[plat].info(f"⏳ **{plat}**  \nScraping...")

    platform_summary = {}

    def on_platform_done(platform: str, count: int, elapsed: float):
        """Called by ScraperManager after each platform finishes."""
        platform_summary[platform] = {"count": count, "elapsed": elapsed}
        if platform in prog_slots:
            if count > 0:
                prog_slots[platform].success(
                    f"✅ **{platform}**  \n{count} products · {elapsed}s"
                )
            else:
                prog_slots[platform].warning(
                    f"⚠️ **{platform}**  \n0 products · {elapsed}s"
                )

    timings = {}

    # Phase 1 — Scraping
    t0 = time.time()
    raw_data = ScraperManager(log).scrape_all(
        q, pin,
        screenshot_dir="",          # screenshots removed from UI
        progress_cb=on_platform_done,
    )
    timings["⚙️  Phase 1 — Scraping (Selenium)"] = round(time.time() - t0, 2)
    st.session_state.raw_data        = raw_data
    st.session_state.platform_summary = platform_summary

    if not raw_data:
        log("❌  No data returned. Try another product or pincode.")
        st.error("No products found."); st.stop()

    # Phase 2 — Kafka
    t0       = time.time()
    kpipeline = KafkaPipeline(log)
    mq_data  = kpipeline.send_and_receive(raw_data)
    timings["📨  Phase 2 — Kafka (message queue)"] = round(time.time() - t0, 2)
    st.session_state.kafka_meta = kpipeline.kafka_meta

    # Phase 3 — Spark / Pandas
    t0 = time.time()
    processed = SparkProcessor(log).process(mq_data)
    timings["⚡  Phase 3 — Spark / Pandas (processing)"] = round(time.time() - t0, 2)

    # Phase 4 — SQLite
    t0 = time.time()
    saved = Database(log).save(processed, q, pin)
    timings["🗄️  Phase 4 — SQLite (storage)"] = round(time.time() - t0, 2)
    timings["🏁  Total"] = round(sum(timings.values()), 2)

    log("\n" + "=" * 62)
    log(f"✅  Pipeline complete — {len(processed)} records processed, {saved} saved to DB")

    st.session_state.results = processed
    st.session_state.timings = timings

    st.rerun()   # re-render so all sections appear with full data

# ── results ───────────────────────────────────────────────────────────────────
if st.session_state.searched:
    results          = st.session_state.results
    raw_data         = st.session_state.raw_data
    timings          = st.session_state.timings
    kafka_meta       = st.session_state.kafka_meta
    platform_summary = st.session_state.platform_summary
    q                = st.session_state.last_q
    pin              = st.session_state.last_pin
    city_lbl         = get_city(pin) or pin
    screenshot_dir   = st.session_state.screenshot_dir

    # ── 1. Terminal (collapsed after search completes) ────────────────────────
    with st.expander("📡 Live Operations Terminal", expanded=False):
        logs = st.session_state.logs
        if logs:
            st.code("\n".join(logs), language="")
        else:
            st.info("Terminal output will appear here after a search.")

    # ── 1b. Platform summary cards (always shown after search) ───────────────
    if platform_summary:
        st.markdown("**🌐 Selenium Scraping — Platform Results**")
        ACTIVE_PLATFORMS = ["Amazon Fresh", "Blinkit", "BigBasket", "Zepto"]
        sum_cols = st.columns(4)
        for i, plat in enumerate(ACTIVE_PLATFORMS):
            with sum_cols[i]:
                info = platform_summary.get(plat, {})
                count   = info.get("count", 0)
                elapsed = info.get("elapsed", "—")
                if count > 0:
                    st.success(f"✅ **{plat}**  \n{count} products · {elapsed}s")
                elif info:
                    st.warning(f"⚠️ **{plat}**  \n0 products · {elapsed}s")
                else:
                    st.info(f"⏳ **{plat}**  \n—")
        st.markdown("")

    # ── 2. Results table ──────────────────────────────────────────────────────
    with st.expander(
        f"📊 Results — {q}  |  {city_lbl} ({pin})  |  {len(results)} products",
        expanded=True
    ):
        if not results:
            st.warning("No results. Run a new search.")
        else:
            in_stock = [r for r in results if r.get("in_stock", True)]
            if in_stock:
                cheapest = min(in_stock, key=lambda r: r.get("price", 9999))
                fastest  = min(in_stock,
                               key=lambda r: (r.get("delivery_mins") or 9999,
                                              r.get("price", 9999)))
                sc1, sc2 = st.columns(2)
                with sc1:
                    st.success(
                        f"💰 **Cheapest:** {cheapest.get('platform')}  ·  "
                        f"{cheapest.get('product_name')}  ·  ₹{cheapest.get('price')}"
                    )
                with sc2:
                    dm = fastest.get("delivery_mins")
                    dm_str = f" · ~{dm} min" if dm else ""
                    st.info(
                        f"⚡ **Fastest delivery:** {fastest.get('platform')}  ·  "
                        f"₹{fastest.get('price')}{dm_str}"
                    )

            st.markdown("&nbsp;")

            # Fallback search URLs — every product gets a working link
            _SEARCH_URLS = {
                "Amazon Fresh" : "https://www.amazon.in/s?k={}&i=grocery",
                "Blinkit"      : "https://blinkit.com/s/?q={}",
                "BigBasket"    : "https://www.bigbasket.com/ps/?q={}",
                "Zepto"        : "https://www.zepto.com/search?query={}",
            }
            def _product_link(r: dict) -> str:
                url = r.get("product_url", "")
                if url:
                    return url
                platform = r.get("platform", "")
                name     = re.sub(r"\s+", "+", r.get("product_name", "").strip())
                tmpl     = _SEARCH_URLS.get(platform, "")
                return tmpl.format(name) if tmpl else ""

            # Determine whether MRP / discount / size / ppu data are useful
            has_mrp  = any(r.get("mrp", 0) > r.get("price", 0) for r in results)
            has_size = any(r.get("size_label", "") for r in results)
            has_ppu  = any(r.get("unit_norm","per pc") != "per pc" for r in results)

            rows = []
            for r in results:
                dm   = r.get("delivery_mins")
                disc = r.get("discount_pct", 0.0)
                vs   = r.get("value_score")
                row = {
                    "Rank"      : r.get("rank", "—"),
                    "Product"   : r.get("product_name", "—"),
                    "Platform"  : r.get("platform", "—"),
                    "Price (₹)" : r.get("price", "—"),
                    "Delivery"  : f"~{dm} min" if dm else "—",
                }
                if has_ppu:
                    ppu  = r.get("price_per_unit")
                    norm = r.get("unit_norm", "per pc")
                    row["₹/unit"]      = f"₹{ppu:.1f} {norm}" if ppu else "—"
                    row["Value Score"] = f"{vs:.2f}" if vs else "—"
                if has_size:
                    row["Size"] = r.get("size_label") or "—"
                if has_mrp:
                    mrp = r.get("mrp", 0)
                    row["MRP (₹)"]  = mrp if mrp > r.get("price", 0) else "—"
                    row["Discount"] = f"{disc:.0f}%" if disc > 0 else "—"
                # Buy link — always present (direct URL or platform search fallback)
                row["Buy"] = _product_link(r)
                rows.append(row)

            df = pd.DataFrame(rows)
            # Sort by rank (already set by value_score in processor)
            try:
                df["_s"] = pd.to_numeric(df["Rank"], errors="coerce").fillna(99)
                df = df.sort_values("_s").drop(columns=["_s"])
            except Exception:
                pass

            col_cfg = {
                "Rank"      : st.column_config.NumberColumn(width="small"),
                "Price (₹)" : st.column_config.NumberColumn(format="₹%.2f"),
                "Delivery"  : st.column_config.TextColumn(width="small"),
                # Buy — always show; renders as clickable link
                "Buy"       : st.column_config.LinkColumn(
                    "🛒 Link", display_text="🛒 Open", width="small",
                    help="Direct product page, or platform search if no direct link",
                ),
            }
            if has_ppu:
                col_cfg["₹/unit"]      = st.column_config.TextColumn(width="medium",
                                          help="Price per 100g / 100mL / piece — for fair comparison")
                col_cfg["Value Score"] = st.column_config.TextColumn(width="small",
                                          help="₹/unit × delivery penalty (15%/hr) — lower is better")
            if has_size:
                col_cfg["Size"]     = st.column_config.TextColumn(width="small")
            if has_mrp:
                col_cfg["MRP (₹)"]  = st.column_config.TextColumn(width="small")
                col_cfg["Discount"] = st.column_config.TextColumn(width="small")

            st.dataframe(df, use_container_width=True, hide_index=True,
                         column_config=col_cfg)
            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️  Download CSV", csv,
                               file_name=f"{q}_{pin}.csv", mime="text/csv")

    # ── 3. Price Bar Chart ────────────────────────────────────────────────────
    with st.expander("📈 Price Comparison Chart", expanded=True):
        if not results:
            st.info("Run a search to see the chart.")
        else:
            try:
                import plotly.express as px
                chart_rows = []
                for r in results:
                    p = r.get("price")
                    if p:
                        chart_rows.append({
                            "Product" : str(r.get("product_name", ""))[:32]
                                        + "  [" + str(r.get("platform", "")) + "]",
                            "Price"   : float(p),
                            "Platform": r.get("platform", ""),
                        })
                if chart_rows:
                    cdf = pd.DataFrame(chart_rows).sort_values("Price")
                    fig = px.bar(
                        cdf, x="Price", y="Product", orientation="h",
                        color="Platform", text="Price",
                        title=f'Live price comparison — "{q}"  ({city_lbl})',
                        labels={"Product": ""},
                        height=max(350, len(cdf) * 26),
                    )
                    fig.update_traces(texttemplate="₹%{text:.0f}", textposition="outside")
                    fig.update_layout(
                        yaxis={"categoryorder": "total ascending"},
                        margin={"l": 8, "r": 60, "t": 45, "b": 8},
                    )
                    st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.caption(f"Chart unavailable: {e}")

    # ── 4. Pipeline Execution Times ───────────────────────────────────────────
    with st.expander("⏱️ Pipeline Execution Times", expanded=True):
        if not timings:
            st.info("Run a search to see pipeline timings.")
        else:
            phase_desc = {
                "⚙️  Phase 1 — Scraping (Selenium)"       : "Headless Chrome scrapes 4 live platforms",
                "📨  Phase 2 — Kafka (message queue)"      : "Produce → topic raw-prices → consume",
                "⚡  Phase 3 — Spark / Pandas (processing)": "Rank, ₹/unit, savings, best-deal flag",
                "🗄️  Phase 4 — SQLite (storage)"           : "Write searches + prices tables to DB",
                "🏁  Total"                                 : "End-to-end wall-clock time",
            }
            t_rows = [
                {"Stage": k, "Description": phase_desc.get(k, ""), "Time (s)": v}
                for k, v in timings.items()
            ]
            st.dataframe(
                pd.DataFrame(t_rows), use_container_width=True, hide_index=True,
                column_config={"Time (s)": st.column_config.NumberColumn(format="%.2f s")},
            )

    # ── 5. Kafka Message Flow ─────────────────────────────────────────────────
    with st.expander("📨 Kafka Message Flow  (Apache Kafka 3.9.2 · KRaft mode)", expanded=True):
        if not kafka_meta:
            st.info("Run a search to see Kafka details.")
        else:
            mode = kafka_meta.get("mode", "unknown")
            mode_badge = "🟢 Real Kafka broker" if mode == "real" else "🟡 In-memory fallback"

            # ── Top metrics row ───────────────────────────────────────────────
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Broker",     kafka_meta.get("broker", "—"))
            k2.metric("Topic",      kafka_meta.get("topic",  "—"))
            k3.metric("Produced",   kafka_meta.get("produced", 0), help="Messages sent by producer")
            k4.metric("Consumed",   kafka_meta.get("consumed", 0), help="Messages read back by consumer")
            k5.metric("Duration",   f"{kafka_meta.get('duration_s', '—')}s")

            st.caption(mode_badge)

            if mode == "real":
                ob = kafka_meta.get("offset_before", 0)
                oa = kafka_meta.get("offset_after",  0)
                part = kafka_meta.get("partition", 0)
                st.code(
                    f"Topic     : {kafka_meta.get('topic')}\n"
                    f"Partition : {part}\n"
                    f"Offset    : {ob}  →  {oa}  (+{oa - ob} new messages)\n"
                    f"Mode      : KRaft (no ZooKeeper)\n"
                    f"Broker    : {kafka_meta.get('broker')}",
                    language=""
                )

            # ── Sample messages table ─────────────────────────────────────────
            sample = kafka_meta.get("sample_msgs", [])
            if sample:
                st.markdown("**Sample messages produced to topic** `raw-prices` ↓")
                # Add an "Offset" column for visual effect
                ob = kafka_meta.get("offset_before", 0)
                rows_with_offset = [
                    {"Offset": ob + i, **m} for i, m in enumerate(sample)
                ]
                st.dataframe(
                    pd.DataFrame(rows_with_offset),
                    use_container_width=True, hide_index=True,
                    column_config={
                        "Offset"  : st.column_config.NumberColumn(width="small"),
                        "price"   : st.column_config.NumberColumn(format="₹%.2f"),
                        "platform": st.column_config.TextColumn(width="medium"),
                    }
                )

    # ── 7. Raw Scraped JSON ───────────────────────────────────────────────────
    with st.expander("🔍 Raw Scraped JSON  (before → after processing)", expanded=False):
        if not raw_data:
            st.info("Run a search to see raw JSON.")
        else:
            n_show = st.slider("Records to display", min_value=5, max_value=len(raw_data),
                               value=min(20, len(raw_data)), step=5)
            ca, cb = st.columns(2)
            with ca:
                st.markdown(f"**🟡 RAW — straight from Selenium** ({len(raw_data)} total)")
                st.caption("Before Kafka / Spark — exactly as scraped")
                raw_s = [
                    {k: v for k, v in r.items()
                     if k in ["platform", "product_name", "price", "mrp",
                              "discount_pct", "size_label", "brand",
                              "delivery_mins", "scraped_at", "source", "pincode"]}
                    for r in raw_data[:n_show]
                ]
                st.code(json.dumps(raw_s, indent=2, default=str), language="json")
                full_raw_json = json.dumps(raw_data, indent=2, default=str).encode("utf-8")
                st.download_button("⬇️  Download Full Raw JSON", full_raw_json,
                                   file_name=f"{q}_{pin}_raw.json", mime="application/json")
            with cb:
                st.markdown(f"**🟢 PROCESSED — after Spark / Pandas** ({len(results)} total)")
                st.caption("Ranked · savings calculated · best-deal flagged")
                proc_s = [
                    {k: v for k, v in r.items()
                     if k in ["platform", "product_name", "price", "mrp",
                              "discount_pct", "rank", "savings", "is_best_deal",
                              "price_per_unit", "unit_norm", "size_label",
                              "processed_at"]}
                    for r in results[:n_show]
                ]
                st.code(json.dumps(proc_s, indent=2, default=str), language="json")
                full_proc_json = json.dumps(results, indent=2, default=str).encode("utf-8")
                st.download_button("⬇️  Download Full Processed JSON", full_proc_json,
                                   file_name=f"{q}_{pin}_processed.json", mime="application/json")

    # ── 8. Search History ─────────────────────────────────────────────────────
    with st.expander("📚 Search History  (SQLite database)", expanded=False):
        try:
            hist = Database(lambda _: None).get_history()
            if hist:
                hdf = pd.DataFrame(hist)[["id", "query", "pincode",
                                          "result_count", "searched_at"]]
                hdf.columns = ["ID", "Query", "Pincode", "Results", "Searched At"]
                st.dataframe(hdf, use_container_width=True, hide_index=True)
            else:
                st.write("No searches yet.")
        except Exception as e:
            st.write(f"Could not load history: {e}")

# ── footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    "**Pipeline:** Selenium → Apache Kafka → Apache Spark / Pandas → SQLite → Streamlit"
)
