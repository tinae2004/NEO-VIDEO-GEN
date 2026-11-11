"""NEO VIDEO GEN — clean LTX-2.3 generation console."""
from pathlib import Path

import gradio as gr

from neo_video_gen.comfy_client import generate_video


def generate(endpoint, workflow_file, prompt, prompt_node, image, image_node, timeout):
    if not workflow_file:
        raise gr.Error("Upload a ComfyUI API-format workflow JSON.")
    if not prompt.strip():
        raise gr.Error("Enter a video prompt.")
    try:
        output = generate_video(
            endpoint,
            Path(workflow_file).read_text(encoding="utf-8"),
            prompt,
            str(prompt_node).strip(),
            str(image) if image else None,
            str(image_node).strip() if image_node else None,
            int(timeout),
        )
    except Exception as exc:
        raise gr.Error(f"Generation failed: {exc}") from exc
    return output, f"Completed: {output}"


with gr.Blocks(title="NEO VIDEO GEN", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🎬 NEO VIDEO GEN\nLTX-2.3 audiovisual generation console")
    gr.Markdown("Connect to a running ComfyUI server with compatible LTX-2.3 models installed.")
    endpoint = gr.Textbox(label="ComfyUI URL", placeholder="http://your-server:8188")
    workflow = gr.File(label="ComfyUI API workflow JSON", file_types=[".json"], type="filepath")
    prompt = gr.Textbox(label="Video and sound prompt", lines=5)
    with gr.Row():
        prompt_node = gr.Textbox(label="Prompt node ID")
        image_node = gr.Textbox(label="Image loader node ID (optional)")
    image = gr.Image(label="Start image (optional)", type="filepath")
    timeout = gr.Slider(label="Timeout (seconds)", minimum=60, maximum=3600, value=1800, step=60)
    button = gr.Button("Generate video", variant="primary")
    result = gr.Video(label="Generated video")
    status = gr.Textbox(label="Job status", interactive=False)
    button.click(generate, [endpoint, workflow, prompt, prompt_node, image, image_node, timeout], [result, status])
    gr.Markdown("---\nGPU rental is not enabled in this initial clean build. Connect a tested GPU worker separately.")

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
