# NEO VIDEO GEN — LTX-2.3 inference on Vast.ai

This is an inference-only pipeline. It does not train, fine-tune, or update LTX weights.

## Reused rental lifecycle

The previous NEO rental pattern is reused: temporary SSH key registration; filtered Vast offer search; local GPU/cost validation; multiple fresh-offer attempts when an offer ID is stale; instance creation; polling for running status; vastai ssh-url; repeated SSH and nvidia-smi preflight; ComfyUI inference through an SSH tunnel; DeepSeek diagnostics on failure; and destroy in a finally block.

The workflow is manually dispatched only. A push to GitHub will not rent a GPU.

## Hardware target

The automatic LTX-2.3 22B inference path requires a full RTX GPU with at least 48GB VRAM; Tesla is excluded. The distilled label does not make this a small model. Current Comfy-Org quantization measurements list roughly 38.6GB peak VRAM for INT8 tensorwise and 29.6GB for NVFP4, still above a 24GB RTX 3090. A 24GB experiment needs a separately validated offload/quantization workflow and is not selected automatically.

## Prerequisites

- Add VAST_API_KEY in repository Actions secrets.
- Optionally add DEEPSEEK_API_KEY; it enables failure diagnosis only.
- The vastai/comfy image or attached persistent volume must already have ComfyUI, LTX-2.3 nodes and compatible distilled model assets.
- Commit an actual ComfyUI API-format workflow JSON (not the normal canvas/editor JSON). Default path: workflows/ltx23_api.json.
- Supply the actual prompt node ID and, for I2V, the actual image-loader node ID and a committed start image.
- An existing Vast volume can be supplied and is mounted at /workspace. Set its actual hourly cost in the workflow input.

## Spend limits

The runner refuses budgets above $3, hourly rates above $0.30, and runtimes above 18 minutes. The estimate includes 25% compute reserve, estimated model download traffic, output upload traffic, the supplied volume charge, and a $0.25 contingency. Missing bandwidth prices cause an offer to be rejected. Provider final invoices may differ.

No GPU is rented unless a verified, rentable, full, on-demand RTX offer passes every hardware and price check.

## Failure agent

DeepSeek receives a redacted error summary and selected remote logs. It identifies the failing stage and suggests a minimal fix. It is advisory only: it cannot run commands, modify files, change caps, rent GPUs or destroy instances. An uncertain failed submission is not retried automatically, avoiding duplicate paid jobs.

## Prepared-environment limitation

This runner expects ComfyUI and the LTX model stack to already exist at the selected ComfyUI root (default /workspace/ComfyUI) on the Vast image or attached volume. It does not download tens of gigabytes of model files during an 18-minute GPU rental. That cache/bootstrap stage must be prepared separately.
