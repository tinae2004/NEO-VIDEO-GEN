# Official LTX-2.3 workflow

NEO includes the upstream Lightricks **LTX-2.3 T2V/I2V single-stage distilled** workflow source at `ltx23_distilled_ui.json`. This is the ComfyUI editor graph, not API prompt JSON. The inference runner must convert it through ComfyUI's UI-to-API workflow converter before submitting it. The positive prompt node is `2483`; the optional image loader node is `2004`.

The graph requires Lightricks `ComfyUI-LTXVideo` and RES4LYF's `ClownSampler_Beta`. It references the `ltx-2.3-22b-dev.safetensors` base checkpoint, the `ltx-2.3-22b-distilled-lora-384-1.1.safetensors` LoRA, `comfy_gemma_3_12B_it.safetensors`, and the LTX audio VAE. These weights must already be present on the ComfyUI image or attached volume; the short paid-run window must not be used to download tens of GB of model files.

The workflow includes audio/video composition and SaveVideo nodes. Begin with a short, low-resolution test. This is a 22B base model plus distilled LoRA workflow, not a tiny standalone distilled checkpoint. Do not assume it fits an RTX 3090; the current 48GB minimum remains conservative until measured quantized/offload tests prove otherwise.
