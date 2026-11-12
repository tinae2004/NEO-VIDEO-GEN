"""GitHub Actions entry point for one LTX-2.3 inference run."""
from __future__ import annotations
import argparse
import os
import sys

from neo_video_gen.vast_inference import (
    MAX_BUDGET_USD, MAX_HOURLY_USD, MAX_RUNTIME_MINUTES, MIN_GPU_VRAM_GB,
    run_ltx_inference,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rent one Vast GPU and generate one LTX-2.3 video.")
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--prompt-node-id", required=True)
    parser.add_argument("--image", default="")
    parser.add_argument("--image-node-id", default="")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--budget-usd", type=float, default=MAX_BUDGET_USD)
    parser.add_argument("--max-hourly-usd", type=float, default=MAX_HOURLY_USD)
    parser.add_argument("--runtime-minutes", type=int, default=MAX_RUNTIME_MINUTES)
    parser.add_argument("--min-vram-gb", type=float, default=MIN_GPU_VRAM_GB)
    parser.add_argument("--disk-gb", type=int, default=100)
    parser.add_argument("--model-download-gb", type=float, default=0.0)
    parser.add_argument("--output-upload-gb", type=float, default=1.0)
    parser.add_argument("--volume-hourly-usd", type=float, default=0.0)
    parser.add_argument("--volume-id", default="")
    parser.add_argument("--comfyui-root", default="/workspace/ComfyUI")
    parser.add_argument("--no-audio-check", action="store_true")
    args = parser.parse_args()

    if not os.environ.get("VAST_API_KEY", "").strip():
        parser.error("VAST_API_KEY must be configured as a GitHub Actions secret")
    try:
        output = run_ltx_inference(
            workflow_path=args.workflow, prompt=args.prompt, prompt_node_id=args.prompt_node_id,
            image_path=args.image or None, image_node_id=args.image_node_id or None,
            timeout_seconds=args.timeout_seconds, require_audio=not args.no_audio_check,
            budget_usd=args.budget_usd, max_hourly_usd=args.max_hourly_usd,
            runtime_minutes=args.runtime_minutes, min_vram_gb=args.min_vram_gb,
            disk_gb=args.disk_gb, model_download_gb=args.model_download_gb,
            output_upload_gb=args.output_upload_gb, volume_hourly_usd=args.volume_hourly_usd,
            volume_id=args.volume_id or os.environ.get("VAST_VOLUME_ID"),
            comfyui_root=args.comfyui_root,
        )
        print("VIDEO_OUTPUT=" + output, flush=True)
        return 0
    except Exception as exc:
        print("LTX inference failed: " + str(exc), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
