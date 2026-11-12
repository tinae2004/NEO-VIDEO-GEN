"""Broad, read-only Vast.ai GPU discovery with local eligibility and cost filters."""
from __future__ import annotations
import json
from dataclasses import asdict, dataclass
from typing import Any
import requests

API_BASE = "https://console.vast.ai/api/v0"
MAX_SEARCH_RESULTS = 500

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
        self.session.headers.update({"Authorization": f"Bearer {api_key.strip()}", "Accept": "application/json"})

    def search_all_offers(self, limit: int = MAX_SEARCH_RESULTS, progress=None) -> list[dict[str, Any]]:
        if not 1 <= limit <= MAX_SEARCH_RESULTS:
            raise ValueError(f"Offer search limit must be between 1 and {MAX_SEARCH_RESULTS}")
        # Official Vast REST API: GET /bundles/?q=<JSON>. Deliberately send
        # no GPU, VRAM, reliability, verification, bandwidth or price filters.
        query = {"limit": limit, "type": "on-demand"}
        if progress:
            progress(f"Requesting up to {limit} marketplace offers with broad GPU discovery.")
        response = self.session.get(f"{API_BASE}/bundles/", params={"q": json.dumps(query)}, timeout=(10, 45))
        if progress:
            progress(f"Vast.ai marketplace replied with HTTP {response.status_code}.")
        if not response.ok:
            raise RuntimeError(f"Vast API HTTP {response.status_code}: {response.text[:1200]}")
        response.raise_for_status()
        payload = response.json()
        offers = payload.get("offers", []) if isinstance(payload, dict) else []
        if not isinstance(offers, list):
            raise RuntimeError(f"Unexpected Vast response shape: {str(payload)[:800]}")
        if progress:
            progress(f"Broad scan returned {len(offers)} offers.")
        return offers

    @staticmethod
    def quote_offer(offer: dict[str, Any], *, disk_gb: float = 100, runtime_minutes: float = 18,
                    ingress_gb: float = 45, egress_gb: float = 1, contingency_usd: float = 0.25) -> OfferQuote | None:
        try:
            name = str(offer["gpu_name"]).strip().replace(" ", "_")
            ram = float(offer["gpu_ram"]) / 1024
            reliability = float(offer["reliability"])
            total_hourly = float(offer["dph_total"])
            base_hourly = float(offer.get("dph_base", offer["dph_total"]))
            storage_rate = float(offer["storage_cost"])
            down_rate = float(offer["inet_down_cost"])
            up_rate = float(offer["inet_up_cost"])
            offer_id = int(offer["id"])
            verified = offer.get("verified") is True or offer.get("verification") == "verified" or offer.get("vericode") == 1
            rentable = offer.get("rentable") is True
            gpu_count = int(offer["num_gpus"])
            gpu_frac = float(offer.get("gpu_frac", 1))
            disk = float(offer["disk_space"])
        except (KeyError, TypeError, ValueError):
            return None
        if "TESLA" in name.upper() or ram < 24 or reliability < .99 or not verified or not rentable:
            return None
        if gpu_count != 1 or gpu_frac < 1 or disk < disk_gb:
            return None
        if min(total_hourly, base_hourly, storage_rate, down_rate, up_rate) < 0:
            return None
        hours = runtime_minutes / 60
        storage_hourly = storage_rate * disk_gb / 730
        compute_cost = max(base_hourly, total_hourly - storage_hourly) * hours
        storage_cost = storage_hourly * hours
        ingress_cost = down_rate * ingress_gb
        egress_cost = up_rate * egress_gb
        total = compute_cost + storage_cost + ingress_cost + egress_cost + contingency_usd
        return OfferQuote(offer_id, name, round(ram, 2), reliability, verified, round(total_hourly, 4),
                          round(compute_cost, 4), round(storage_cost, 4), round(ingress_cost, 4),
                          round(egress_cost, 4), round(contingency_usd, 4), round(total, 4))

    def affordable_quotes(self, *, budget_usd: float = 3, max_hourly_usd: float = .30,
                          disk_gb: float = 100, runtime_minutes: float = 18,
                          ingress_gb: float = 45, egress_gb: float = 1, progress=None) -> list[OfferQuote]:
        if not 0 < budget_usd <= 3:
            raise ValueError("Budget must be greater than 0 and no more than 3 USD")
        if not 0 < max_hourly_usd <= .30:
            raise ValueError("Hourly cap must be greater than 0 and no more than 0.30 USD")
        if not 0 < runtime_minutes <= 18:
            raise ValueError("Runtime cap must be greater than 0 and no more than 18 minutes")
        if disk_gb < 100:
            raise ValueError("Disk estimate must reserve at least 100 GB")
        offers = self.search_all_offers(progress=progress)
        quotes = []
        stats = {"tesla_excluded": 0, "vram_too_low": 0, "reliability_low": 0, "unverified_or_unrentable": 0,
                 "partial_or_multi_gpu": 0, "disk_too_small": 0, "missing_cost_fields": 0,
                 "hourly_too_high": 0, "total_too_high": 0}
        if progress:
            progress(f"Applying local filters to all {len(offers)} returned offers.")
        for i, offer in enumerate(offers, 1):
            name = str(offer.get("gpu_name", "unknown")).replace(" ", "_")
            try:
                ram = float(offer.get("gpu_ram", 0)) / 1024
                reliability = float(offer.get("reliability", 0))
                count = int(offer.get("num_gpus", 0))
                fraction = float(offer.get("gpu_frac", 1))
                disk = float(offer.get("disk_space", 0))
                verified = offer.get("verified") is True or offer.get("verification") == "verified" or offer.get("vericode") == 1
                rentable = offer.get("rentable") is True
            except (TypeError, ValueError):
                stats["missing_cost_fields"] += 1
                continue
            reason = None
            if "TESLA" in name.upper():
                stats["tesla_excluded"] += 1; reason = "Tesla GPU excluded"
            elif ram < 24:
                stats["vram_too_low"] += 1; reason = f"{ram:.1f}GB VRAM; need 24GB+"
            elif reliability < .99:
                stats["reliability_low"] += 1; reason = f"reliability {reliability:.3f}; need 0.99+"
            elif not verified or not rentable:
                stats["unverified_or_unrentable"] += 1; reason = "not verified or not rentable"
            elif count != 1 or fraction < 1:
                stats["partial_or_multi_gpu"] += 1; reason = "not one full GPU"
            elif disk < disk_gb:
                stats["disk_too_small"] += 1; reason = f"{disk:.0f}GB disk; need {disk_gb:.0f}GB"
            if reason:
                if progress and i <= 40: progress(f"Reject {offer.get('id', '?')} ({name}): {reason}.")
                continue
            quote = self.quote_offer(offer, disk_gb=disk_gb, runtime_minutes=runtime_minutes,
                                     ingress_gb=ingress_gb, egress_gb=egress_gb)
            if quote is None:
                stats["missing_cost_fields"] += 1
                if progress and i <= 40: progress(f"Reject {offer.get('id', '?')} ({name}): missing price/storage/bandwidth fields.")
            elif quote.hourly_rate_usd > max_hourly_usd:
                stats["hourly_too_high"] += 1
                if progress and i <= 40: progress(f"Reject {quote.offer_id} ({name}): hourly rate {quote.hourly_rate_usd:.4f} exceeds cap.")
            elif quote.estimated_total_usd > budget_usd:
                stats["total_too_high"] += 1
                if progress and i <= 40: progress(f"Reject {quote.offer_id} ({name}): total {quote.estimated_total_usd:.4f} exceeds budget; bandwidth included.")
            else:
                quotes.append(quote)
                if progress:
                    progress(f"PASS {quote.offer_id} {name}: {quote.gpu_ram_gb:.1f}GB, hourly={quote.hourly_rate_usd:.4f}, bandwidth={quote.ingress_usd + quote.egress_usd:.4f}, total={quote.estimated_total_usd:.4f} USD.")
        if progress:
            progress("Filter summary: " + ", ".join(f"{k}={v}" for k, v in stats.items()) + f", passed={len(quotes)}.")
        preferred = {"RTX_3090": 0, "RTX_4090": 1}
        return sorted(quotes, key=lambda q: (preferred.get(q.gpu_name, 2), q.estimated_total_usd,
                                             q.ingress_usd + q.egress_usd, -q.reliability))
