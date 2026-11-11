"""Run a read-only Vast.ai GPU offer and cost preflight."""
from __future__ import annotations

import json
import os
import sys

from neo_video_gen.vast_client import VastClient


def main() -> int:
    api_key = os.environ.get("VAST_API_KEY", "")
    if not api_key:
        print("ERROR: Configure the VAST_API_KEY GitHub Actions secret.")
        return 2
    client = VastClient(api_key)
    try:
        quotes = client.affordable_quotes()
    except Exception as exc:
        print(f"ERROR: Vast offer preflight failed: {exc}")
        return 1
    if not quotes:
        print(
            "NO SAFE OFFER FOUND. No GPU was rented. At least one price component "
            "may be missing, or no verified RTX 3090/4090 meets the full $3 estimate."
        )
        return 3
    payload = [quote.to_dict() for quote in quotes]
    print(json.dumps(payload, indent=2))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("# NEO VIDEO GEN — Vast.ai preflight\n\n")
            summary.write("| GPU | Offer | Est. compute | Storage | Ingress | Egress | Total |\n")
            summary.write("|---|---:|---:|---:|---:|---:|---:|\n")
            for q in payload:
                summary.write(
                    f"| {q['gpu_name']} | {q['offer_id']} | "
                    f"${q['compute_usd']:.4f} | ${q['storage_usd']:.4f} | "
                    f"${q['ingress_usd']:.4f} | ${q['egress_usd']:.4f} | "
                    f"${q['estimated_total_usd']:.4f} |\n"
                )
            summary.write("\n**Read-only check: no instance was created.**\n")
    print("READ-ONLY CHECK COMPLETE: no instance was created.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
