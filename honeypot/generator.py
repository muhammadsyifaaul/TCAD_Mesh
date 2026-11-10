"""
honeypot/generator.py
Deterministic fake data generator for the honeypot.

SECURITY RULES (AGENTS.md §4.4):
  - Every field is derived from HMAC(secret, identity + field_key).
  - Given the same (secret, identity), output is always identical — deterministic.
  - Given a different identity, output is completely different — no correlation.
  - ZERO forbidden words in any output value:
      forbidden = {simulated, honeypot, fake, pending_*, test, dummy, mock}
  - Honeytoken IDs share the EXACT format as real IDs: DOC-<12 hex chars>
"""
import hashlib
import hmac
import struct
from datetime import datetime, timezone, timedelta


# ── Vocabulary pools — all realistic Indonesian logistics terms ────────────────
_ORIGINS = [
    "Jakarta Warehouse A", "Jakarta Warehouse C", "Bandung Distribution Center",
    "Medan Warehouse B", "Semarang Port Terminal", "Surabaya Cold Storage",
    "Makassar Logistics Depot", "Palembang Hub East", "Denpasar Cargo Center",
    "Balikpapan Industrial Zone",
]
_DESTINATIONS = [
    "Surabaya Hub 3", "Yogyakarta Retail Hub", "Pekanbaru Central",
    "Bali Logistics Center", "Makassar Port", "Manado Distribution",
    "Kupang Warehouse", "Pontianak Regional Hub", "Samarinda Depot",
    "Jayapura Receiving Station",
]
_CARRIERS = [
    "Nusantara Express", "Garuda Cargo", "Pelni Freight",
    "Tiki Logistics", "JNE Industrial", "Wahana Cargo",
    "Anteraja Freight", "SiCepat Industrial", "Lion Parcel",
    "RPX Holdings",
]
_STATUSES = ["pending", "in_transit", "delivered", "cancelled"]
_LOCATIONS = [
    "Semarang Transfer Hub", "Surabaya Port", "Cirebon Junction",
    "Bandung Relay Station", "Solo Distribution Point", "Malang Depot",
    "Banjarmasin Transit Hub", "Batam Free Trade Zone",
]
_SKUS = [
    ("SKU-0042-B", "Automotive spare parts"),
    ("SKU-0117-A", "Industrial fasteners"),
    ("SKU-0223-C", "Textile rolls"),
    ("SKU-0098-D", "Electronic components"),
    ("SKU-0301-F", "Construction materials"),
    ("SKU-0445-G", "Packaged food goods"),
    ("SKU-0512-H", "Pharmaceutical supplies"),
    ("SKU-0633-J", "Agricultural equipment"),
    ("SKU-0744-K", "Office furniture"),
    ("SKU-0855-L", "Electrical wiring"),
]
_TRACKING_MESSAGES = [
    "Shipment dispatched from origin warehouse",
    "Package arrived at transfer hub",
    "Customs clearance completed",
    "Loaded onto vessel",
    "Trans-shipment complete",
    "Package out for delivery",
    "Delivery attempted — recipient unavailable",
    "Package delivered and signed for",
]


class HoneypotGenerator:
    """
    Deterministic fake data generator seeded per (secret, identity).
    All public methods are pure — calling them multiple times with the same
    (secret, identity) MUST return identical results.
    """

    def __init__(self, secret: str, identity: str):
        self._secret = secret.encode()
        self._identity = identity.encode()

    # ── Core: deterministic integer from a namespaced key ─────────────────────
    def _int(self, key: str, modulo: int) -> int:
        """Returns a stable integer in [0, modulo) for (secret, identity, key)."""
        sig = hmac.new(
            self._secret,
            self._identity + b":" + key.encode(),
            hashlib.sha256,
        ).digest()
        # Use first 8 bytes as uint64 — uniform distribution
        val = struct.unpack(">Q", sig[:8])[0]
        return val % modulo

    def _hex_id(self, key: str) -> str:
        """Returns 12 deterministic hex chars for an ID field."""
        sig = hmac.new(
            self._secret,
            self._identity + b":" + key.encode(),
            hashlib.sha256,
        ).hexdigest()
        return sig[:12]

    def _date(self, key: str, base_days_ago: int = 10) -> str:
        """Returns an ISO 8601 UTC datetime string, stable per key."""
        offset_hours = self._int(key + ":h", base_days_ago * 24)
        dt = datetime(2026, 11, 1, 8, 0, 0, tzinfo=timezone.utc) - timedelta(hours=offset_hours)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _pick(self, key: str, pool: list):
        return pool[self._int(key, len(pool))]

    # ── Shipments ─────────────────────────────────────────────────────────────
    def shipments(self, count: int = 5) -> list:
        result = []
        for i in range(count):
            ns = f"ship:{i}"
            doc_id = f"DOC-{self._hex_id(ns + ':id')}"
            mnf_id = f"MNF-{self._hex_id(ns + ':mnf')}"
            rte_id = f"RTE-{self._hex_id(ns + ':rte')}"
            status = self._pick(ns + ":status", _STATUSES)
            result.append({
                "id": doc_id,
                "status": status,
                "origin": self._pick(ns + ":origin", _ORIGINS),
                "destination": self._pick(ns + ":dest", _DESTINATIONS),
                "carrier": self._pick(ns + ":carrier", _CARRIERS),
                "weight_kg": round(1.0 + self._int(ns + ":wt", 2990) / 10.0, 1),
                "created_at": self._date(ns + ":cat", 20),
                "updated_at": self._date(ns + ":uat", 5),
                "manifest_id": mnf_id,
                "route_id": rte_id if status != "pending" else None,
            })
        return result

    # ── Manifests ─────────────────────────────────────────────────────────────
    def manifests(self, count: int = 5) -> list:
        ships = self.shipments(count)
        result = []
        for i, s in enumerate(ships):
            ns = f"mnf:{i}"
            sku_idx = self._int(ns + ":sku", len(_SKUS))
            sku_code, sku_desc = _SKUS[sku_idx]
            qty = 10 + self._int(ns + ":qty", 490)
            unit_wt = round(0.1 + self._int(ns + ":uwt", 990) / 1000.0, 3)
            total_wt = round(qty * unit_wt, 2)
            result.append({
                "id": s["manifest_id"],
                "shipment_id": s["id"],
                "items": [
                    {
                        "sku": sku_code,
                        "description": sku_desc,
                        "quantity": qty,
                        "unit_weight_kg": unit_wt,
                    }
                ],
                "total_weight_kg": total_wt,
                "created_at": self._date(ns + ":cat", 21),
            })
        return result

    # ── Routes ────────────────────────────────────────────────────────────────
    def routes(self, count: int = 3) -> list:
        ships = self.shipments(count)
        result = []
        for i, s in enumerate(ships):
            if s["status"] == "pending":
                continue
            ns = f"rte:{i}"
            stop_count = 2 + self._int(ns + ":stops", 2)
            stops = []
            for j in range(stop_count):
                stops.append({
                    "location": self._pick(f"{ns}:loc:{j}", _LOCATIONS),
                    "eta": self._date(f"{ns}:eta:{j}", 15 - j * 3),
                    "arrived_at": self._date(f"{ns}:arr:{j}", 14 - j * 3)
                    if j < stop_count - 1 else None,
                })
            result.append({
                "id": s["route_id"],
                "shipment_id": s["id"],
                "stops": stops,
                "created_at": self._date(ns + ":cat", 22),
            })
        return result

    # ── Tracking ──────────────────────────────────────────────────────────────
    def tracking(self, shipment_id: str) -> list:
        ns = f"track:{shipment_id}"
        event_count = 1 + self._int(ns + ":cnt", 4)
        events = []
        for i in range(event_count):
            events.append({
                "ts": self._date(f"{ns}:ts:{i}", 10 - i),
                "location": self._pick(f"{ns}:loc:{i}", _LOCATIONS),
                "status": self._pick(f"{ns}:st:{i}", _STATUSES),
                "message": self._pick(f"{ns}:msg:{i}", _TRACKING_MESSAGES),
            })
        return events
