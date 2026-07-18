"""
kafka_pipeline.py
-----------------
Kafka Producer + Consumer for the price comparison pipeline.

What it does:
  1. Producer  → serialises each product as JSON → sends to 'raw-prices' topic
  2. Consumer  → reads back from 'raw-prices' topic
  3. If Kafka is not running → falls back to in-memory pass-through
     (terminal shows exactly what happened)

Topic used: raw-prices
"""

import json
import os
import time
from datetime import datetime
from typing import List, Dict, Callable


KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TOPIC_RAW       = os.getenv("KAFKA_TOPIC_RAW", "raw-prices")


class KafkaPipeline:
    def __init__(self, log_callback: Callable):
        self.log        = log_callback
        self._producer  = None
        self._available = False
        self.kafka_meta = {}   # populated after send_and_receive(); readable by app.py
        self._try_connect()

    # ── Connection ─────────────────────────────────────────────────────────────
    def _try_connect(self):
        try:
            from kafka import KafkaProducer, KafkaConsumer
            from kafka.errors import NoBrokersAvailable

            test_producer = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
                key_serializer=lambda k: k.encode("utf-8"),
                request_timeout_ms=3000,
                max_block_ms=3000,
            )
            test_producer.close()
            self._available = True
            self.log(f"  [Kafka] ✅ Connected to broker at {KAFKA_BOOTSTRAP}")
        except Exception as e:
            self._available = False
            reason = str(e)[:80]
            if "No module" in reason:
                reason = "kafka-python not installed"
            elif "NoBrokers" in reason or "connect" in reason.lower():
                reason = f"no broker running at {KAFKA_BOOTSTRAP}"
            self.log(f"  [Kafka] ⚠️  Broker not available — {reason}")
            self.log(f"  [Kafka]    Using in-memory pass-through (pipeline continues normally)")

    # ── Main API ───────────────────────────────────────────────────────────────
    def send_and_receive(self, products: List[Dict]) -> List[Dict]:
        """
        Send all products to Kafka and read them back.
        Falls back gracefully if Kafka is unavailable.
        After this call, inspect self.kafka_meta for UI display.
        """
        self.log("\n" + "=" * 52)
        self.log("PHASE 2 — KAFKA PIPELINE")
        self.log(f"Broker  : {KAFKA_BOOTSTRAP}")
        self.log(f"Topic   : {TOPIC_RAW}")
        self.log(f"Messages: {len(products)}")
        self.log("=" * 52)

        if not products:
            self.log("  [Kafka] No products to send")
            self.kafka_meta = {"mode": "none", "messages_in": 0, "messages_out": 0}
            return []

        t_start = time.time()
        if self._available:
            result = self._kafka_roundtrip(products)
        else:
            result = self._memory_passthrough(products)

        # Store metadata for UI display
        duration = round(time.time() - t_start, 2)
        self.kafka_meta["duration_s"]  = duration
        self.kafka_meta["messages_in"] = len(products)
        self.kafka_meta["messages_out"]= len(result)
        self.kafka_meta["broker"]      = KAFKA_BOOTSTRAP
        self.kafka_meta["topic"]       = TOPIC_RAW
        # Sample messages for display (first 6, key fields only)
        self.kafka_meta["sample_msgs"] = [
            {k: v for k, v in p.items()
             if k in ["platform", "product_name", "price", "size_label", "source"]}
            for p in products[:6]
        ]
        return result

    # ── Real Kafka path ────────────────────────────────────────────────────────
    def _kafka_roundtrip(self, products: List[Dict]) -> List[Dict]:
        from kafka import KafkaProducer, KafkaConsumer, TopicPartition

        # ── Snapshot current end offsets BEFORE producing ─────────────────────
        # This ensures we only consume the messages WE produce, not stale ones
        # from previous runs sitting in the topic.
        probe = KafkaConsumer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            consumer_timeout_ms=3000,
        )
        try:
            partitions = probe.partitions_for_topic(TOPIC_RAW) or {0}
            tps = [TopicPartition(TOPIC_RAW, p) for p in partitions]
            probe.assign(tps)
            probe.seek_to_end(*tps)
            start_offsets = {tp: probe.position(tp) for tp in tps}
        finally:
            probe.close()
        self.log(f"  [Kafka] Snapshot offsets before produce: {dict(start_offsets)}")

        # ── Produce ──────────────────────────────────────────────────────────
        self.log(f"  [Kafka] Producing {len(products)} messages → topic '{TOPIC_RAW}'")
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8"),
            acks="all",
            retries=3,
        )
        sent = 0
        for p in products:
            key = f"{p.get('platform','')}:{p.get('product_name','')}:{p.get('size_label','')}"
            producer.send(TOPIC_RAW, key=key, value=p)
            sent += 1
        producer.flush()
        producer.close()
        self.log(f"  [Kafka] ✅ {sent} messages published to '{TOPIC_RAW}'")

        # ── Consume — seek to the offset snapshot (only our fresh messages) ───
        self.log(f"  [Kafka] Consuming {sent} fresh messages from '{TOPIC_RAW}'...")
        time.sleep(1.0)

        consumer = KafkaConsumer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            consumer_timeout_ms=8000,
            enable_auto_commit=False,
        )
        consumer.assign(list(start_offsets.keys()))
        for tp, offset in start_offsets.items():
            consumer.seek(tp, offset)

        consumed = []
        for msg in consumer:
            consumed.append(msg.value)
            if len(consumed) >= sent:
                break
        consumer.close()

        self.log(f"  [Kafka] ✅ {len(consumed)} messages consumed from '{TOPIC_RAW}'")
        self.log(f"  [Kafka] Offsets: {dict(start_offsets)} → +{sent} new messages")

        # Expose offset info for the UI Kafka flow panel
        first_tp = list(start_offsets.keys())[0]
        self.kafka_meta = {
            "mode"         : "real",
            "broker"       : KAFKA_BOOTSTRAP,
            "topic"        : TOPIC_RAW,
            "partition"    : first_tp.partition,
            "offset_before": start_offsets[first_tp],
            "offset_after" : start_offsets[first_tp] + sent,
            "produced"     : sent,
            "consumed"     : len(consumed),
        }
        return consumed if consumed else products  # fallback if consume was empty

    # ── Fallback path ──────────────────────────────────────────────────────────
    def _memory_passthrough(self, products: List[Dict]) -> List[Dict]:
        self.log(f"  [Kafka] FALLBACK: Simulating Kafka message flow in-memory")
        self.log(f"  [Kafka] Serialising {len(products)} records to JSON...")
        serialised   = [json.dumps(p, default=str).encode("utf-8") for p in products]
        deserialised = [json.loads(s.decode("utf-8")) for s in serialised]
        self.log(f"  [Kafka] {len(serialised)} messages serialised (JSON, UTF-8)")
        self.log(f"  [Kafka] {len(deserialised)} messages deserialised")
        self.log(f"  [Kafka] ✅ Pass-through complete — {len(deserialised)} records ready")
        self.kafka_meta = {
            "mode"     : "in-memory",
            "broker"   : KAFKA_BOOTSTRAP,
            "topic"    : TOPIC_RAW,
            "partition": 0,
            "offset_before": 0,
            "offset_after" : 0,
            "produced" : len(serialised),
            "consumed" : len(deserialised),
        }
        return deserialised
