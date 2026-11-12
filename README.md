# NEO VIDEO GEN

An inference-only LTX-2.3 audiovisual generation project. The active application does not train or fine-tune model weights.

## Current architecture

- Gradio generation console for ComfyUI
- ComfyUI API workflow submission and output retrieval
- Audio-track verification with `ffprobe`
- Read-only Vast marketplace preflight
- Separate, manually triggered Vast.ai rental + LTX-2.3 inference workflow
- DeepSeek failure diagnostics for provisioning and generation errors

The previous NEO-LTX-2.3 project is preserved under `legacy/NEO-LTX-2.3/` for reference. Its Blender/data/training code is archived and is not connected to the active video-generation path.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://localhost:7860`.

## Generate through an existing ComfyUI server

1. Start ComfyUI with compatible LTX-2.3 nodes and distilled model assets installed.
2. Export a workflow as **API-format JSON**.
3. Enter the ComfyUI URL and upload the JSON in the Gradio app.
4. Set the actual prompt node ID from the workflow.
5. Optionally select the image loader node and upload a start image.
6. Keep audio verification enabled for audiovisual output.

## Generate using a rented Vast GPU

The workflow `.github/workflows/ltx-vast-generate.yml` is the inference-only rental path. It reuses the previous NEO rental lifecycle:

1. Register a temporary SSH key and search fresh on-demand Vast offers.
2. Recheck GPU, verification, rentable state, full allocation, reliability, bandwidth and total cost locally.
3. Try multiple offers and refresh stale offer IDs.
4. Rent one instance, wait for running status, obtain `vastai ssh-url`, and retry SSH plus `nvidia-smi`.
5. Start/check ComfyUI, open an SSH tunnel, submit one LTX video workflow, and collect the output.
6. On failure, send redacted logs to the DeepSeek diagnostic adviser.
7. Destroy the instance in a `finally` cleanup path.

This workflow runs only when manually dispatched from GitHub Actions; ordinary code pushes do not rent GPUs.

### Required preparation

- Add `VAST_API_KEY` as a repository Actions secret.
- Add `DEEPSEEK_API_KEY` as a repository Actions secret to enable the failure adviser. DeepSeek is advisory only; it does not modify code, change spending limits, or operate Vast infrastructure.
- Commit the actual ComfyUI **API-format** workflow JSON as `workflows/ltx23_api.json` (or supply another committed path when dispatching).
- The workflow must use actual node IDs from that JSON.
- ComfyUI, LTX-2.3 nodes and compatible distilled model files must already be installed on the selected Vast image or attached persistent volume. The rental path does not download multi-tens-of-GB weights during the short metered runtime.
- For a persistent volume, supply its existing ID and its actual hourly cost. It is attached at `/workspace`.
- The default ComfyUI root is `/workspace/ComfyUI`.

### Hardware and spend safeguards

The automatic 22B inference path requires a full RTX GPU with at least 48GB VRAM and excludes Tesla. Quantized LTX-2.3 measurements still exceed a 24GB card's physical VRAM for the usual paths; a 24GB RTX 3090 experiment requires a separately verified offload/quantization workflow.

The code refuses a budget above **$3 total**, hourly price above **$0.30**, runtime above **18 minutes**, VRAM below **48GB**, non-RTX/Tesla cards, partial GPU allocations, unreliable, unverified or currently non-rentable offers, and offers with missing required network price fields. A 25% compute reserve and $0.25 contingency are included. The volume hourly charge must be supplied accurately. These calculations are estimates, not a guarantee of the provider's final bill.

## Validation status

The latest GitHub Actions safety test run passed Python compilation and all 7 inference-offer unit tests. This proves the local filters behave as tested; it does **not** prove a live Vast rental or finished video generation. No GPU was rented by the unit tests.

The first real inference run still requires the actual API workflow JSON and a prepared ComfyUI/LTX model cache. The older read-only Vast preflight remains separate and does not create instances.
