"""Read-only Vast.ai offer discovery and conservative cost estimation.

This module intentionally does not rent instances. It rejects offers when any
cost component required for the user's budget estimate is missing.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

import requests

API_BASE = "https://console.vast.ai/api/v0"


@dataclass(frozen=True)
class OfferQuote:
    offer_id: int
    gpu_name: str
    gpu_ram_gb: float
    reliability: float
    verified: bool
    hourly_rate_usd: float
    compute_usd: float
    storage_usd: float
    ingress_usd: float
    egress_usd: float
    contingency_usd: float
    estimated_total_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VastClient:
    def __init__(self, api_key: str, session: requests.Session | None = None):
        if not api_key or not api_key.strip():
            raise ValueError("VAST_API_KEY is required")
        self.session = session or requests.Session()
        self.session.headers.update(
            {"Authorization": f"Bearer {api_key.strip()}", "Accept": "application/json"}
        )

    def search_model(self, gpu_name: str, limit: int = 50) -> list[dict[str, Any]]:
        if gpu_name not in {"RTX_3090", "RTX_4090"}:
            raise ValueError("Only RTX_3090 and RTX_4090 are allowed")
        query = json.dumps({"gpu_name": gpu_name, "num_gpus": 1, "limit": limit})
        response = self.session.get(
            f"{API_BASE}/bundles/",
            params={"q": query},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        offers = payload.get("offers", []) if isinstance(payload, dict) else []
        if not isinstance(offers, list):
            raise RuntimeError("Vast returned an unexpected offer response")
        return offers

    @staticmethod
    def quote_offer(
        offer: dict[str, Any],
        *,
        disk_gb: float = 100,
        runtime_minutes: float = 18,
        ingress_gb: float = 45,
        egress_gb: float = 1,
        contingency_usd: float = 0.25,
    ) -> OfferQuote | None:
        """Return a quote only when every requested price and eligibility field is known."""
        try:
            gpu_name = str(offer.get("gpu_name", "")).replace(" ", "_")
            gpu_ram = float(offer["gpu_ram"])
            reliability = float(offer["reliability"])
            hourly_value = offer.get("dph_total")
            if hourly_value is None:
                hourly_value = offer["dph"]
            hourly = float(hourly_value)
            storage_per_gb_month = float(offer["storage_cost"])
            ingress_per_gb = float(offer["inet_down_cost"])
            egress_per_gb = float(offer["inet_up_cost"])
            offer_id = int(offer["id"])
            verified = offer["verified"] is True
            rentable = offer["rentable"] is True
            num_gpus = int(offer.get("num_gpus", 1))
            disk_space = float(offer.get("disk_space", 0))
        except (KeyError, TypeError, ValueError):
            return None

        if gpu_name not in {"RTX_3090", "RTX_4090"}:
            return None
        if gpu_ram < 24 or reliability < 0.99 or not verified or not rentable:
            return None
        if num_gpus != 1 or disk_space < disk_gb:
            return None
        if min(hourly, storage_per_gb_month, ingress_per_gb, egress_per_gb) < 0:
            return None

        hours = runtime_minutes / 60.0
        # Vast's storage field is documented as $/GB/month. 730 hours is a
        # conservative conventional month divisor for a short runtime estimate.
        compute_cost = hourly * hours
        storage_cost = storage_per_gb_month * disk_gb * hours / 730.0
        ingress_cost = ingress_per_gb * ingress_gb
        egress_cost = egress_per_gb * egress_gb
        total = compute_cost + storage_cost + ingress_cost + egress_cost + contingency_usd

        return OfferQuote(
            offer_id=offer_id,
            gpu_name=gpu_name,
            gpu_ram_gb=gpu_ram,
            reliability=reliability,
            verified=verified,
            hourly_rate_usd=round(hourly, 4),
            compute_usd=round(compute_cost, 4),
            storage_usd=round(storage_cost, 4),
            ingress_usd=round(ingress_cost, 4),
            egress_usd=round(egress_cost, 4),
            contingency_usd=round(contingency_usd, 4),
            estimated_total_usd=round(total, 4),
        )

    def affordable_quotes(
        self,
        *,
        budget_usd: float = 3.0,
        max_hourly_usd: float = 0.30,
        disk_gb: float = 100,
        runtime_minutes: float = 18,
        ingress_gb: float = 45,
        egress_gb: float = 1,
    ) -> list[OfferQuote]:
        if budget_usd <= 0 or budget_usd > 3.0:
            raise ValueError("Budget must be greater than $0 and no more than $3")
        if max_hourly_usd <= 0 or max_hourly_usd > 0.30:
            raise ValueError("Hourly cap must be greater than $0 and no more than $0.30")
        if runtime_minutes <= 0 or runtime_minutes > 18:
            raise ValueError("Runtime cap must be greater than 0 and no more than 18 minutes")
        if disk_gb < 100:
            raise ValueError("Disk estimate must reserve at least 100 GB for model assets")

        # Prefer a 3090; only search the 4090 fallback when no qualifying
        # 3090 offer survives all known-cost checks.
        for gpu_name in ("RTX_3090", "RTX_4090"):
            quotes = []
            for offer in self.search_model(gpu_name):
                quote = self.quote_offer(
                    offer,
                    disk_gb=disk_gb,
                    runtime_minutes=runtime_minutes,
                    ingress_gb=ingress_gb,
                    egress_gb=egress_gb,
                )
                if quote and float(offer.get("dph_total") if offer.get("dph_total") is not None else offer.get("dph", 999999)) <= max_hourly_usd:
                    if quote.estimated_total_usd <= budget_usd:
                        quotes.append(quote)
            if quotes:
                return sorted(quotes, key=lambda q: (q.estimated_total_usd, -q.reliability))
        return []
