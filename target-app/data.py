"""
target-app/data.py
Static mock dataset for the logistics API.
Data is realistic (Indonesian logistics context) but entirely fictional.
"""
import math

# ── Helpers ───────────────────────────────────────────────────────────────────
def paginate(data: list, page: int, limit: int) -> dict:
    total = len(data)
    start = (page - 1) * limit
    end = start + limit
    return {
        "data": data[start:end],
        "pagination": {"page": page, "limit": limit, "total": total},
    }


# ── Shipments ─────────────────────────────────────────────────────────────────
SHIPMENTS = [
    {
        "id": "DOC-1a2b3c4d5e6f",
        "status": "in_transit",
        "origin": "Jakarta Warehouse A",
        "destination": "Surabaya Hub 3",
        "carrier": "Nusantara Express",
        "weight_kg": 14.5,
        "created_at": "2026-11-01T08:00:00Z",
        "updated_at": "2026-11-05T14:30:00Z",
        "manifest_id": "MNF-4a3b2c1d0e9f",
        "route_id": "RTE-1a2b3c4d5e6f",
    },
    {
        "id": "DOC-2b3c4d5e6f7a",
        "status": "delivered",
        "origin": "Bandung Distribution Center",
        "destination": "Yogyakarta Retail Hub",
        "carrier": "Garuda Cargo",
        "weight_kg": 32.0,
        "created_at": "2026-10-28T07:30:00Z",
        "updated_at": "2026-11-02T09:15:00Z",
        "manifest_id": "MNF-5b4c3d2e1f0a",
        "route_id": "RTE-2b3c4d5e6f7a",
    },
    {
        "id": "DOC-3c4d5e6f7a8b",
        "status": "pending",
        "origin": "Medan Warehouse B",
        "destination": "Pekanbaru Central",
        "carrier": "Nusantara Express",
        "weight_kg": 8.75,
        "created_at": "2026-11-06T11:00:00Z",
        "updated_at": "2026-11-06T11:00:00Z",
        "manifest_id": "MNF-6c5d4e3f2a1b",
        "route_id": None,
    },
    {
        "id": "DOC-4d5e6f7a8b9c",
        "status": "in_transit",
        "origin": "Semarang Port Terminal",
        "destination": "Bali Logistics Center",
        "carrier": "Pelni Freight",
        "weight_kg": 210.0,
        "created_at": "2026-11-03T06:00:00Z",
        "updated_at": "2026-11-07T02:00:00Z",
        "manifest_id": "MNF-7d6e5f4a3b2c",
        "route_id": "RTE-4d5e6f7a8b9c",
    },
    {
        "id": "DOC-5e6f7a8b9c0d",
        "status": "cancelled",
        "origin": "Jakarta Warehouse C",
        "destination": "Makassar Port",
        "carrier": "Garuda Cargo",
        "weight_kg": 55.0,
        "created_at": "2026-10-25T14:00:00Z",
        "updated_at": "2026-10-26T09:30:00Z",
        "manifest_id": "MNF-8e7f6a5b4c3d",
        "route_id": None,
    },
]


# ── Manifests ─────────────────────────────────────────────────────────────────
MANIFESTS = [
    {
        "id": "MNF-4a3b2c1d0e9f",
        "shipment_id": "DOC-1a2b3c4d5e6f",
        "items": [
            {"sku": "SKU-0042-B", "description": "Automotive spare parts", "quantity": 120, "unit_weight_kg": 0.08},
            {"sku": "SKU-0117-A", "description": "Industrial fasteners", "quantity": 500, "unit_weight_kg": 0.012},
        ],
        "total_weight_kg": 15.6,
        "created_at": "2026-11-01T07:55:00Z",
    },
    {
        "id": "MNF-5b4c3d2e1f0a",
        "shipment_id": "DOC-2b3c4d5e6f7a",
        "items": [
            {"sku": "SKU-0223-C", "description": "Textile rolls (cotton)", "quantity": 40, "unit_weight_kg": 0.8},
        ],
        "total_weight_kg": 32.0,
        "created_at": "2026-10-28T07:25:00Z",
    },
    {
        "id": "MNF-6c5d4e3f2a1b",
        "shipment_id": "DOC-3c4d5e6f7a8b",
        "items": [
            {"sku": "SKU-0098-D", "description": "Electronic components", "quantity": 35, "unit_weight_kg": 0.25},
        ],
        "total_weight_kg": 8.75,
        "created_at": "2026-11-06T10:50:00Z",
    },
    {
        "id": "MNF-7d6e5f4a3b2c",
        "shipment_id": "DOC-4d5e6f7a8b9c",
        "items": [
            {"sku": "SKU-0301-F", "description": "Construction materials (tile)", "quantity": 420, "unit_weight_kg": 0.5},
        ],
        "total_weight_kg": 210.0,
        "created_at": "2026-11-03T05:50:00Z",
    },
    {
        "id": "MNF-8e7f6a5b4c3d",
        "shipment_id": "DOC-5e6f7a8b9c0d",
        "items": [
            {"sku": "SKU-0445-G", "description": "Packaged food goods", "quantity": 110, "unit_weight_kg": 0.5},
        ],
        "total_weight_kg": 55.0,
        "created_at": "2026-10-25T13:45:00Z",
    },
]


# ── Routes ────────────────────────────────────────────────────────────────────
ROUTES = [
    {
        "id": "RTE-1a2b3c4d5e6f",
        "shipment_id": "DOC-1a2b3c4d5e6f",
        "stops": [
            {"location": "Jakarta Warehouse A", "eta": "2026-11-01T08:00:00Z", "arrived_at": "2026-11-01T08:00:00Z"},
            {"location": "Semarang Transfer Hub", "eta": "2026-11-03T10:00:00Z", "arrived_at": "2026-11-03T09:47:00Z"},
            {"location": "Surabaya Hub 3", "eta": "2026-11-05T14:00:00Z", "arrived_at": None},
        ],
        "created_at": "2026-11-01T08:05:00Z",
    },
    {
        "id": "RTE-2b3c4d5e6f7a",
        "shipment_id": "DOC-2b3c4d5e6f7a",
        "stops": [
            {"location": "Bandung Distribution Center", "eta": "2026-10-28T07:30:00Z", "arrived_at": "2026-10-28T07:30:00Z"},
            {"location": "Yogyakarta Retail Hub", "eta": "2026-11-02T09:00:00Z", "arrived_at": "2026-11-02T09:15:00Z"},
        ],
        "created_at": "2026-10-28T07:35:00Z",
    },
    {
        "id": "RTE-4d5e6f7a8b9c",
        "shipment_id": "DOC-4d5e6f7a8b9c",
        "stops": [
            {"location": "Semarang Port Terminal", "eta": "2026-11-03T06:00:00Z", "arrived_at": "2026-11-03T06:00:00Z"},
            {"location": "Surabaya Port", "eta": "2026-11-05T08:00:00Z", "arrived_at": "2026-11-05T07:50:00Z"},
            {"location": "Bali Logistics Center", "eta": "2026-11-07T06:00:00Z", "arrived_at": None},
        ],
        "created_at": "2026-11-03T06:10:00Z",
    },
]


# ── Tracking ──────────────────────────────────────────────────────────────────
TRACKING = {
    "DOC-1a2b3c4d5e6f": [
        {"ts": "2026-11-01T08:00:00Z", "location": "Jakarta Warehouse A", "status": "in_transit", "message": "Shipment dispatched from origin warehouse"},
        {"ts": "2026-11-03T09:47:00Z", "location": "Semarang Transfer Hub", "status": "in_transit", "message": "Package arrived at transfer hub"},
    ],
    "DOC-2b3c4d5e6f7a": [
        {"ts": "2026-10-28T07:30:00Z", "location": "Bandung Distribution Center", "status": "in_transit", "message": "Shipment dispatched"},
        {"ts": "2026-11-02T09:15:00Z", "location": "Yogyakarta Retail Hub", "status": "delivered", "message": "Package delivered and signed for"},
    ],
    "DOC-4d5e6f7a8b9c": [
        {"ts": "2026-11-03T06:00:00Z", "location": "Semarang Port Terminal", "status": "in_transit", "message": "Loaded onto vessel MV Kartini III"},
        {"ts": "2026-11-05T07:50:00Z", "location": "Surabaya Port", "status": "in_transit", "message": "Trans-shipment complete"},
    ],
}
