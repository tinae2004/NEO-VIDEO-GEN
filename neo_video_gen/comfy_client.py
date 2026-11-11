"""Submit a ComfyUI API workflow and verify/download its video output."""
from __future__ import annotations

import json
import mimetypes
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".avi"}


def _validate_endpoint(base_url: str) -> str:
    parsed = urlsplit((base_url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("ComfyUI URL must be an absolute http:// or https:// URL")
    if parsed.username or parsed.password:
        raise ValueError("Do not put credentials in the ComfyUI URL")
    return base_url.strip().rstrip("/") + "/"


def probe_audio_stream(path: str | Path) -> bool:
    """Return True only when ffprobe confirms at least one audio stream."""
    executable = shutil.which("ffprobe")
    if not executable:
        raise RuntimeError(
            "ffprobe is not installed, so NEO cannot verify the audio track. "
            "Install FFmpeg/ffprobe on the ComfyUI host or disable 'Require audio'."
        )
    result = subprocess.run(
        [
            executable,
            "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe could not inspect the generated file: {result.stderr[-500:]}")
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("ffprobe returned invalid JSON while checking audio") from exc
    return bool(payload.get("streams"))


def _video_outputs(record: dict, allow_gif: bool):
    outputs = record.get("outputs", {})
    if not isinstance(outputs, dict):
        return
    keys = ("videos", "gifs") if allow_gif else ("videos",)
    for node_id, node in outputs.items():
        if not isinstance(node, dict):
            continue
        for key in keys:
            items = node.get(key, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict) or not item.get("filename"):
                    continue
                filename = str(item["filename"])
                suffix = Path(filename).suffix.lower()
                if suffix not in VIDEO_EXTENSIONS:
                    continue
                yield node_id, item


def generate_video(
    base_url: str,
    workflow_json: str,
    prompt: str,
    prompt_node_id: str,
    image_path: str | None = None,
    image_node_id: str | None = None,
    timeout_seconds: int = 1800,
    require_audio: bool = True,
) -> str:
    base = _validate_endpoint(base_url)
    if not isinstance(timeout_seconds, int) or timeout_seconds < 1:
        raise ValueError("Timeout must be a positive integer")
    if not prompt or not prompt.strip():
        raise ValueError("Prompt cannot be empty")

    workflow = json.loads(workflow_json)
    if not isinstance(workflow, dict) or not workflow:
        raise ValueError("Workflow must be a non-empty API-format JSON object")
    if prompt_node_id not in workflow or not isinstance(workflow[prompt_node_id], dict):
        raise ValueError(f"Prompt node {prompt_node_id!r} is not in the workflow")
    inputs = workflow[prompt_node_id].get("inputs", {})
    if not isinstance(inputs, dict):
        raise ValueError("Prompt node inputs must be an object")
    fields = [
        key for key, value in inputs.items()
        if isinstance(value, str) and key.lower() in {"text", "prompt"}
    ]
    if not fields:
        raise ValueError("Selected prompt node has no text or prompt input")
    inputs[fields[0]] = prompt

    with requests.Session() as session:
        if image_path:
            if not image_node_id or image_node_id not in workflow:
                raise ValueError("Select a valid image loader node when uploading a start image")
            path = Path(image_path)
            if not path.is_file():
                raise ValueError("Selected start image does not exist")
            image_inputs = workflow[image_node_id].setdefault("inputs", {})
            if not isinstance(image_inputs, dict) or "image" not in image_inputs:
                raise ValueError("Selected image node has no 'image' input")
            with path.open("rb") as handle:
                response = session.post(
                    urljoin(base, "upload/image"),
                    files={
                        "image": (
                            path.name,
                            handle,
                            mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                        )
                    },
                    data={"type": "input", "overwrite": "true"},
                    timeout=120,
                )
            response.raise_for_status()
            filename = response.json().get("name")
            if not filename:
                raise RuntimeError("ComfyUI image upload returned no filename")
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
            history = response.json()
            record = history.get(prompt_id) if isinstance(history, dict) else None
            if record:
                status = record.get("status", {})
                if isinstance(status, dict) and status.get("status_str") == "error":
                    raise RuntimeError(f"ComfyUI failed: {status.get('messages', [])}")

                candidates = list(_video_outputs(record, allow_gif=not require_audio))
                if candidates:
                    for node_id, item in candidates:
                        query = {
                            "filename": item["filename"],
                            "subfolder": item.get("subfolder", ""),
                            "type": item.get("type", "output"),
                        }
                        media = session.get(urljoin(base, "view"), params=query, timeout=300)
                        media.raise_for_status()
                        if not media.content:
                            raise RuntimeError("ComfyUI returned an empty video file")
                        suffix = Path(item["filename"]).suffix.lower()
                        destination = Path("outputs") / f"neo_{prompt_id[:8]}{suffix}"
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(media.content)
                        if require_audio and not probe_audio_stream(destination):
                            destination.unlink(missing_ok=True)
                            raise RuntimeError(
                                "The generated file has no audio stream. Check the LTX audio "
                                "conditioning and video-combine/save node in the workflow."
                            )
                        return str(destination.resolve())

                if isinstance(status, dict) and status.get("completed"):
                    raise RuntimeError(
                        "ComfyUI completed the job but returned no supported video file. "
                        "The workflow must save an MP4/WebM/MOV/MKV/AVI video."
                    )
            time.sleep(3)

    raise TimeoutError(f"ComfyUI job {prompt_id} exceeded {timeout_seconds}s")
