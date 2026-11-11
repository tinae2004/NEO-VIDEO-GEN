# NEO VIDEO GEN

A clean LTX-2.3 audiovisual generation console. This repository deliberately excludes the legacy FastFrame/Blender training pipeline.

## Current architecture

- Gradio web console
- ComfyUI API workflow submission
- LTX-2.3 text-to-video / image-to-video workflow support
- Polling and output download
- Lightweight manually triggered CI

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
6. Generate and inspect the returned media.

The app does not claim to rent a GPU. GPU provisioning is a separate integration and is not enabled until Vast.ai credentials and a tested LTX worker launcher are configured.

## 24GB RTX 3090 test policy

Begin with a short 480p clip. Record peak VRAM, wall time, output duration and audio track presence. Do not assume 720p or long clips fit. Quantization and offloading must be validated against the exact ComfyUI nodes and RTX 3090/Ampere support.

## Safety and spending

No GPU is rented automatically by this app. Add a dedicated GPU workflow only after its total budget cap, runtime cap, provider minimum billing, storage and cleanup behavior have been tested.
