# NEO VIDEO GEN

A clean LTX-2.3 audiovisual generation console. This repository deliberately excludes the legacy FastFrame/Blender training pipeline.

## Current architecture

- Gradio generation console for a running ComfyUI server
- ComfyUI API workflow submission and output retrieval
- Audio-track verification with `ffprobe` enabled by default
- Read-only Vast.ai offer discovery and conservative cost preflight
- Manually triggered CPU-only CI and a separate read-only Vast preflight workflow

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://localhost:7860`.

## Generate

1. Start a ComfyUI server with a compatible LTX-2.3 workflow and model files installed.
2. Export the workflow as API-format JSON.
3. Enter the ComfyUI URL and upload the JSON.
4. Set the actual prompt node ID from that workflow.
5. Optionally set the image loader node ID and upload a start image.
6. Keep **Require and verify an audio track** enabled for audiovisual generation. The ComfyUI host must have `ffprobe` available.

The client refuses to report success as audiovisual when an audio stream is absent or cannot be checked. The exact workflow still needs to be validated against the installed LTX-2.3 nodes; the application cannot infer arbitrary workflow node IDs.

## Vast.ai preflight

The workflow `.github/workflows/vast-preflight.yml` searches current RTX 3090 offers first and RTX 4090 only as a fallback. It uses the current Vast REST API with a bearer token stored in the repository Actions secret `VAST_API_KEY`.

To configure it:
1. In GitHub, open **Settings → Secrets and variables → Actions**.
2. Add a repository secret named `VAST_API_KEY`. Never paste the key into source files, issue comments, or chat.
3. Open **Actions → NEO VIDEO GEN — Vast.ai Offer Preflight → Run workflow**.

The preflight is read-only: it never rents or creates an instance. It rejects offers that do not provide the required GPU model, 24GB VRAM, 99% reliability, verified/rentable status, at least 100GB disk, and all required price fields. It estimates 18 minutes of compute, 100GB storage, 45GB ingress, 1GB egress, and a $0.25 contingency; it enforces a $0.30/hour and $3 total estimate ceiling.

**Important:** bandwidth is usage-based, and the estimate assumes the stated data transfer allowance. A runtime overrun, larger model download, unplanned output transfer, or provider-side billing adjustment can exceed an estimate. The preflight does not guarantee a hard account-wide spending limit.

## GPU rental status

No GPU is rented automatically. A real rental workflow must first identify the exact ComfyUI/LTX-2.3 container/template, its API workflow JSON, model dependencies, boot time, and cleanup behavior. Only then should a metered instance creation step be added. Stopping a Vast instance does not end storage charges; the instance must be destroyed when finished.
