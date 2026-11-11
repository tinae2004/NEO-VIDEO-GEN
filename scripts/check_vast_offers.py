"""Run a read-only Vast.ai GPU offer and cost preflight with live step logs."""
from __future__ import annotations
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from neo_video_gen.vast_client import VastClient

def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    print(f"[{stamp}] {message}", flush=True)

def main() -> int:
    log("NEO VIDEO GEN preflight started. READ-ONLY; GPU rental is disabled.")
    api_key = os.environ.get("VAST_API_KEY", "")
    if not api_key:
        log("FAIL: VAST_API_KEY is missing or empty. Add it under GitHub Actions secrets.")
        return 2
    log("PASS: VAST_API_KEY is present; value will not be printed.")
    client = VastClient(api_key)
    try:
        log("Guardrails: <=$3 total, <=$0.30/hour, <=18 minutes, >=100GB disk.")
        quotes = client.affordable_quotes(progress=log)
    except Exception as exc:
        log(f"FAIL: {type(exc).__name__}: {exc}")
        log("Full traceback follows:")
        traceback.print_exc()
        return 1
    if not quotes:
        log("FAIL: No offer passed all GPU, reliability, verification, price and cost checks.")
        log("No GPU was rented. Review candidate rejection lines above.")
        return 3
    payload = [quote.to_dict() for quote in quotes]
    log(f"PASS: Found {len(payload)} affordable offer(s).")
    print(json.dumps(payload, indent=2), flush=True)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("# NEO VIDEO GEN — Vast.ai preflight\n\n")
            summary.write("| GPU | Offer | Est. compute | Storage | Ingress | Egress | Total |\n")
            summary.write("|---|---:|---:|---:|---:|---:|---:|\n")
            for q in payload:
                summary.write(
                    f"| {q['gpu_name']} | {q['offer_id']} | "
                    f"\${q['compute_usd']:.4f} | \${q['storage_usd']:.4f} | "
                    f"\${q['ingress_usd']:.4f} | \${q['egress_usd']:.4f} | "
                    f"\${q['estimated_total_usd']:.4f} |\n"
                )
            summary.write("\n**Read-only check: no instance was created.**\n")
    log("READ-ONLY CHECK COMPLETE: no instance was created.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
