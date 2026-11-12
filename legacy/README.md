# Legacy repository snapshot

This directory contains a file-for-file copy of the previous `NEO-LTX-2.3` repository branch.

- Source: https://github.com/tinae2004/NEO-LTX-2.3/tree/neo-video-gen
- Source commit: `e2248f4867e7ef2edbe48c2de099fd90f429916d`
- Imported files: 46
- Purpose: preserve the previous Blender capture, motion/dataset research, temporal utilities, translator, training code, docs, and tests without replacing the current NEO VIDEO GEN app or Vast preflight.

## Important safety note

The archived `scripts/run_vast_gpu_training.py` contains code that can create and destroy paid Vast.ai GPU instances. It is kept only as historical source. It is not connected to the current app or active workflows, has not been executed as part of this import, and must not be run until its offer filters, cost estimates, and spend limits are independently reviewed.

The archived project is not itself a working end-to-end LTX video generator. Its Blender-to-translator components are research/data tooling; the generation console still depends on a running ComfyUI endpoint.
