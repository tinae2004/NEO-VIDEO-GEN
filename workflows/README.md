# RTX 3090 / LTX-2.3 GGUF workflow

NEO includes an RTX 3090-compatible LTX-2.3 GGUF distilled T2V graph at
`ltx23_gguf_t2v_distilled_3090_ui.json`. Positive prompt node: `4`.
The graph uses 960x544, 121 frames (about 5 seconds at 24fps), a Q4_0 GGUF
video model, distilled LoRA, Gemma-3 text encoder, text projection, video VAE
and audio VAE.

Required ComfyUI custom nodes:
- Lightricks ComfyUI-LTXVideo
- city96 ComfyUI-GGUF
- The workflow-to-API converter endpoint used by the runner

**Important:** The RTX 3090 path is inference-only. It does not download the
large model assets during the paid run. The following files must already exist
in the matching ComfyUI model folders: `ltx-2.3-22b-dev-Q4_0.gguf`,
`ltx-2.3-22b-distilled-1.1_lora-dynamic_fro09_avg_rank_111_bf16.safetensors`,
`gemma-3-12b-it-ablit-norms-biproj-fp8mixed.safetensors`,
`ltx-2-3-22b-text_encoder.safetensors`, `LTX23_video_vae_bf16.safetensors`,
and `LTX23_audio_vae_bf16.safetensors`.

The reported warm RTX 3090 example is about 94 seconds for 960x544x121 at
8 steps. That is not an end-to-end rental guarantee; cold start, model loading,
and output transfer add time. The runner keeps the $3 total estimate cap,
$0.30/hour GPU cap, 18-minute runtime cap, 99% reliability, verified/rentable
full-GPU and no-Tesla filters. If the cached model assets or required nodes are
missing, the run must fail rather than silently download tens of GB.
