"""Submit a ComfyUI API workflow and download its generated video."""
from __future__ import annotations

import json
import mimetypes
import time
from pathlib import Path
from urllib.parse import urljoin

import requests


def generate_video(
    base_url: str,
    workflow_json: str,
    prompt: str,
    prompt_node_id: str,
    image_path: str | None = None,
    image_node_id: str | None = None,
    timeout_seconds: int = 1800,
) -> str:
    if not base_url.strip().startswith(("http://", "https://")):
        raise ValueError("ComfyUI URL must start with http:// or https://")
    base = base_url.strip().rstrip("/") + "/"
    workflow = json.loads(workflow_json)
    if not isinstance(workflow, dict) or not workflow:
        raise ValueError("Workflow must be a non-empty API-format JSON object")
    if prompt_node_id not in workflow:
        raise ValueError(f"Prompt node {prompt_node_id!r} is not in the workflow")
    inputs = workflow[prompt_node_id].get("inputs", {})
    fields = [k for k, v in inputs.items() if isinstance(v, str) and k.lower() in {"text", "prompt"}]
    if not fields:
        raise ValueError("Selected prompt node has no text or prompt input")
    inputs[fields[0]] = prompt
    session = requests.Session()

    if image_path:
        if not image_node_id or image_node_id not in workflow:
            raise ValueError("Select a valid image loader node when uploading a start image")
        path = Path(image_path)
        with path.open("rb") as handle:
            response = session.post(
                urljoin(base, "upload/image"),
                files={"image": (path.name, handle, mimetypes.guess_type(path.name)[0] or "application/octet-stream")},
                data={"type": "input", "overwrite": "true"},
                timeout=120,
            )
        response.raise_for_status()
        filename = response.json().get("name")
        if not filename:
            raise RuntimeError("ComfyUI image upload returned no filename")
        image_inputs = workflow[image_node_id].setdefault("inputs", {})
        if "image" not in image_inputs:
            raise ValueError("Selected image node has no 'image' input")
        image_inputs["image"] = filename

    response = session.post(urljoin(base, "prompt"), json={"prompt": workflow}, timeout=120)
    response.raise_for_status()
    prompt_id = response.json().get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI returned no prompt_id: {response.text[:500]}")

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = session.get(urljoin(base, f"history/{prompt_id}"), timeout=60)
        response.raise_for_status()
        record = response.json().get(prompt_id)
        if record:
            status = record.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(f"ComfyUI failed: {status.get('messages', [])}")
            for node in record.get("outputs", {}).values():
                for key in ("videos", "gifs"):
                    for item in node.get(key, []):
                        query = {
                            "filename": item["filename"],
                            "subfolder": item.get("subfolder", ""),
                            "type": item.get("type", "output"),
                        }
                        media = session.get(urljoin(base, "view"), params=query, timeout=180)
                        media.raise_for_status()
                        suffix = Path(item["filename"]).suffix or ".mp4"
                        destination = Path("outputs") / f"neo_{prompt_id[:8]}{suffix}"
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(media.content)
                        return str(destination.resolve())
            if status.get("completed"):
                raise RuntimeError("Job completed without video output. Ensure workflow saves a video.")
        time.sleep(3)
    raise TimeoutError(f"ComfyUI job {prompt_id} exceeded {timeout_seconds}s")
