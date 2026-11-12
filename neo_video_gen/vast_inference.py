"""Budget-capped Vast.ai orchestration for LTX-2.3 inference only (no training)."""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from neo_video_gen.comfy_client import generate_video
from neo_video_gen.diagnostics import analyze_failure, redact

API_BASE = "https://console.vast.ai/api/v0"
MAX_BUDGET_USD = 3.00
MAX_HOURLY_USD = 0.30
MAX_RUNTIME_MINUTES = 18
MIN_GPU_VRAM_GB = 24.0
DEFAULT_DISK_GB = 100
VAST_IMAGE = "vastai/comfy"


def number(value: Any, default: float | None = None) -> float | None:
    try:
        return default if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return default


def is_verified(offer: dict[str, Any]) -> bool:
    return (offer.get("verified") is True or offer.get("verification") == "verified"
            or offer.get("vericode") == 1)


@dataclass(frozen=True)
class OfferQuote:
    offer_id: int
    gpu_name: str
    gpu_vram_gb: float
    reliability: float
    hourly_usd: float
    compute_reserve_usd: float
    download_usd: float
    upload_usd: float
    volume_reserve_usd: float
    contingency_usd: float
    total_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def quote_offer(
    offer: dict[str, Any], *, min_vram_gb: float = MIN_GPU_VRAM_GB,
    max_hourly_usd: float = MAX_HOURLY_USD, budget_usd: float = MAX_BUDGET_USD,
    runtime_minutes: float = MAX_RUNTIME_MINUTES, disk_gb: float = DEFAULT_DISK_GB,
    model_download_gb: float = 0.0, output_upload_gb: float = 1.0,
    volume_hourly_usd: float = 0.0, contingency_usd: float = 0.25,
) -> OfferQuote | None:
    name = str(offer.get("gpu_name", "")).strip()
    if not name or "RTX" not in name.upper() or "TESLA" in name.upper():
        return None

    # Vast's API examples use gpu_ram=24000 for a 24GB card; units are MB.
    vram_mb = number(offer.get("gpu_ram"), 0.0) or 0.0
    vram_gb = vram_mb / 1000.0
    reliability = number(offer.get("reliability"))
    hourly = number(offer.get("dph_total"))
    disk = number(offer.get("disk_space"))
    gpu_count = number(offer.get("num_gpus"))
    gpu_fraction = number(offer.get("gpu_frac"))
    down_rate = number(offer.get("inet_down_cost"))
    up_rate = number(offer.get("inet_up_cost"))
    offer_id = number(offer.get("id"))

    if (
        offer_id is None or vram_gb < min_vram_gb or reliability is None or reliability < 0.99
        or hourly is None or hourly <= 0 or hourly > max_hourly_usd
        or disk is None or disk < disk_gb or gpu_count != 1
        or gpu_fraction is None or gpu_fraction < 1.0
        or not is_verified(offer) or offer.get("rentable") is not True
        or (model_download_gb > 0 and down_rate is None)
        or (output_upload_gb > 0 and up_rate is None)
    ):
        return None

    hours = runtime_minutes / 60.0
    compute = hourly * hours * 1.25
    download = (down_rate or 0.0) * model_download_gb
    upload = (up_rate or 0.0) * output_upload_gb
    volume = volume_hourly_usd * hours
    total = compute + download + upload + volume + contingency_usd
    if total > budget_usd:
        return None

    return OfferQuote(
        offer_id=int(offer_id), gpu_name=name, gpu_vram_gb=round(vram_gb, 2),
        reliability=reliability, hourly_usd=round(hourly, 4),
        compute_reserve_usd=round(compute, 4), download_usd=round(download, 4),
        upload_usd=round(upload, 4), volume_reserve_usd=round(volume, 4),
        contingency_usd=round(contingency_usd, 4), total_usd=round(total, 4),
    )


def eligible_offers(offers: list[dict[str, Any]], *, progress=None, **limits) -> list[OfferQuote]:
    stats = {"non_rtx_or_tesla": 0, "vram_too_low": 0, "reliability_low": 0,
             "not_verified_or_not_rentable": 0, "not_full_single_gpu": 0,
             "disk_too_small": 0, "price_or_cost_rejected": 0}
    quotes: list[OfferQuote] = []
    min_vram = limits.get("min_vram_gb", MIN_GPU_VRAM_GB)
    for offer in offers:
        name = str(offer.get("gpu_name", "unknown"))
        vram = (number(offer.get("gpu_ram"), 0.0) or 0.0) / 1000.0
        reason = None
        if "RTX" not in name.upper() or "TESLA" in name.upper():
            stats["non_rtx_or_tesla"] += 1
            reason = "not an RTX card or Tesla is excluded"
        elif vram < min_vram:
            stats["vram_too_low"] += 1
            reason = "below " + str(min_vram) + "GB VRAM target"
        elif (number(offer.get("reliability"), 0.0) or 0.0) < 0.99:
            stats["reliability_low"] += 1
            reason = "reliability below 99%"
        elif not is_verified(offer) or offer.get("rentable") is not True:
            stats["not_verified_or_not_rentable"] += 1
            reason = "not verified and rentable"
        elif number(offer.get("num_gpus")) != 1 or (number(offer.get("gpu_frac")) or 0.0) < 1:
            stats["not_full_single_gpu"] += 1
            reason = "not one full GPU"
        elif (number(offer.get("disk_space"), 0.0) or 0.0) < limits.get("disk_gb", DEFAULT_DISK_GB):
            stats["disk_too_small"] += 1
            reason = "disk below minimum"
        if reason:
            if progress:
                progress("Reject " + str(offer.get("id", "?")) + " (" + name + "): " + reason)
            continue

        quote = quote_offer(offer, **limits)
        if quote is None:
            stats["price_or_cost_rejected"] += 1
            if progress:
                progress("Reject " + str(offer.get("id", "?")) + " (" + name
                         + "): hourly/total budget or bandwidth price check failed")
            continue
        quotes.append(quote)
        if progress:
            progress("Eligible " + str(quote.offer_id) + " " + quote.gpu_name
                     + ": VRAM=" + str(quote.gpu_vram_gb) + "GB, hourly=$"
                     + str(quote.hourly_usd) + ", estimated total=$" + str(quote.total_usd))

    preferred = ("RTX 3090", "RTX 4090", "RTX A6000", "RTX 6000 ADA", "RTX PRO 6000")
    def sort_key(q: OfferQuote):
        normalized = q.gpu_name.upper().replace("_", " ")
        rank = next((i for i, item in enumerate(preferred) if item in normalized), len(preferred))
        return rank, q.total_usd, -q.reliability
    if progress:
        progress("Offer filter summary: " + json.dumps(stats) + "; passed=" + str(len(quotes)))
    return sorted(quotes, key=sort_key)


class VastAPI:
    def __init__(self, api_key: str):
        if not api_key.strip():
            raise ValueError("VAST_API_KEY is missing")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": "Bearer " + api_key.strip(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.request(method, API_BASE + path, json=payload, timeout=(10, 45))
        if not response.ok:
            raise RuntimeError("Vast API " + method + " " + path + " failed ("
                               + str(response.status_code) + "): " + redact(response.text[:1000]))
        if response.status_code == 204 or not response.text.strip():
            return {}
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Unexpected Vast API response shape")
        return data

    def search_offers(self, min_vram_gb: float, disk_gb: int) -> list[dict[str, Any]]:
        # Reuse the previous NEO filtered POST /bundles rental pattern.
        query = {
            "gpu_ram": {"gte": int(min_vram_gb * 1000)},
            "num_gpus": {"gte": 1},
            "disk_space": {"gte": disk_gb},
            "reliability": {"gte": 0.99},
            "direct_port_count": {"gte": 1},
            "verified": {"eq": True},
            "rentable": {"eq": True},
            "type": "ondemand",
            "limit": 30,
        }
        offers = self.request("POST", "/bundles/", query).get("offers", [])
        if not isinstance(offers, list):
            raise RuntimeError("Vast /bundles did not return an offers list")
        return offers

    def create_instance(self, quote: OfferQuote, disk_gb: int, volume_id: str | None) -> int:
        payload: dict[str, Any] = {
            "image": VAST_IMAGE,
            "label": "NEO-LTX23-Inference-" + str(int(time.time())),
            "disk": disk_gb,
            "runtype": "ssh_direct",
            "cancel_unavail": True,
        }
        if volume_id:
            payload["volume_info"] = {"volume_id": int(volume_id), "mount_path": "/workspace"}
        result = self.request("PUT", "/asks/" + str(quote.offer_id) + "/", payload)
        if result.get("new_contract") is None:
            raise RuntimeError("Vast did not return new_contract: " + json.dumps(result)[:800])
        return int(result["new_contract"])

    def get_instance(self, instance_id: int) -> dict[str, Any]:
        data = self.request("GET", "/instances/" + str(instance_id) + "/")
        instance = data.get("instances", data)
        if isinstance(instance, list):
            instance = next((x for x in instance if int(x.get("id", -1)) == instance_id), {})
        return instance if isinstance(instance, dict) else {}

    def destroy(self, instance_id: int) -> None:
        self.request("DELETE", "/instances/" + str(instance_id) + "/")


def rent_with_refresh(api: VastAPI, *, volume_id: str | None = None, progress=None, **limits):
    excluded: set[int] = set()
    last_error: Exception | None = None
    attempts = 0
    for search_no in range(1, 6):
        if progress:
            progress("Vast offer refresh " + str(search_no) + "/5")
        offers = api.search_offers(limits["min_vram_gb"], limits["disk_gb"])
        quotes = eligible_offers(offers, progress=progress, **limits)
        candidates = [q for q in quotes if q.offer_id not in excluded]
        if progress:
            progress("Fresh offers=" + str(len(offers)) + "; safe candidates=" + str(len(candidates)))
        if not candidates:
            if search_no < 5:
                time.sleep(min(search_no * 2, 8))
                continue
            break
        refresh = False
        for quote in candidates[:8]:
            attempts += 1
            if progress:
                progress("Attempting offer " + str(quote.offer_id) + " " + quote.gpu_name
                         + " at $" + str(quote.hourly_usd) + "/hour")
            try:
                return api.create_instance(quote, limits["disk_gb"], volume_id), quote
            except Exception as exc:
                last_error = exc
                excluded.add(quote.offer_id)
                if progress:
                    progress("Rental attempt failed: " + redact(str(exc)))
                if any(token in str(exc).lower()
                       for token in ("no_such_ask", "not available", "404/3603", "offer not found")):
                    refresh = True
                    break
        if search_no < 5:
            time.sleep(min(search_no * 2, 8) if refresh else 1)
    if last_error:
        raise RuntimeError("No safe offer rented after " + str(attempts)
                           + " attempts. Last error: " + str(last_error)) from last_error
    raise RuntimeError("No offer passed RTX, full-GPU, VRAM, verification, reliability and cost checks.")


def _run(command: list[str], env: dict[str, str], timeout: int = 60) -> str:
    result = subprocess.run(command, env=env, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout or "")[-2500:]
        raise RuntimeError("Command failed (" + str(result.returncode) + "): "
                           + shlex.join(command) + "\n" + redact(detail))
    return (result.stdout or "").strip()


def _ssh_agent(env: dict[str, str]) -> None:
    result = subprocess.run(["ssh-agent", "-s"], text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=15, check=True)
    for key, value in re.findall(r"(SSH_AUTH_SOCK|SSH_AGENT_PID)=([^;]+);", result.stdout):
        env[key] = value
    if "SSH_AUTH_SOCK" not in env:
        raise RuntimeError("Could not start ssh-agent")


def _ssh_base(instance_id: int, key_path: Path, known_hosts: Path, env: dict[str, str]) -> list[str]:
    raw = _run(["vastai", "ssh-url", str(instance_id)], env, 30)
    opts = ["-i", str(key_path), "-o", "IdentitiesOnly=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "UserKnownHostsFile=" + str(known_hosts), "-o", "ConnectTimeout=15"]
    if raw.startswith("ssh://"):
        parsed = urlparse(raw)
        if not parsed.hostname or not parsed.port:
            raise RuntimeError("Invalid SSH URL returned by Vast")
        return ["ssh", *opts, "-p", str(parsed.port),
                (parsed.username or "root") + "@" + parsed.hostname]
    tokens = shlex.split(raw)
    if tokens and tokens[0] == "ssh":
        tokens = tokens[1:]
    if not tokens:
        raise RuntimeError("Vast returned an empty SSH connection command")
    return ["ssh", *opts, *tokens]


def _remote(ssh_base: list[str], script: str, env: dict[str, str], timeout: int = 60) -> str:
    return _run(ssh_base + ["bash -lc " + shlex.quote(script)], env, timeout)


def _wait_running(api: VastAPI, instance_id: int, deadline: float, progress=None) -> None:
    while time.monotonic() < deadline:
        record = api.get_instance(instance_id)
        status = str(record.get("actual_status", record.get("status", ""))).lower()
        if progress:
            progress("Vast instance " + str(instance_id) + " status=" + (status or "unknown"))
        if status == "running":
            return
        if status in {"dead", "error", "exited", "deleted", "stopped"}:
            raise RuntimeError("Vast instance reached terminal status: " + status)
        time.sleep(15)
    raise TimeoutError("Vast instance did not reach running state before boot deadline")


def _gpu_check(ssh_base: list[str], env: dict[str, str], min_vram_gb: float) -> str:
    result = _remote(ssh_base,
        "nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits", env, 30)
    rows = [x.strip() for x in result.splitlines() if x.strip()]
    if not rows:
        raise RuntimeError("nvidia-smi returned no GPU")
    names = []
    for row in rows:
        parts = [x.strip() for x in row.split(",")]
        if len(parts) < 2:
            continue
        name, memory_mb = parts[0], number(parts[1], 0.0) or 0.0
        if "TESLA" in name.upper():
            raise RuntimeError("Tesla GPU detected; policy excludes Tesla")
        if memory_mb < min_vram_gb * 1000:
            raise RuntimeError("Actual GPU VRAM below " + str(min_vram_gb) + "GB: " + row)
        names.append(name + " " + str(round(memory_mb / 1024, 1)) + "GiB")
    return "; ".join(names)


def _start_comfyui(ssh_base: list[str], env: dict[str, str], root: str) -> None:
    # Install only workflow runtime node packs and the UI-to-API converter.
    # Model weights are never downloaded in this short paid session.
    script = (
        "set -euo pipefail; ROOT=" + shlex.quote(root) + "; "
        "test -f \"$ROOT/main.py\" || { echo 'ComfyUI main.py missing at '\"$ROOT\"; exit 31; }; "
        "mkdir -p \"$ROOT/custom_nodes\"; cd \"$ROOT/custom_nodes\"; "
        "clone_if_missing(){ if [ ! -d \"$1/.git\" ]; then git clone --depth 1 \"$2\" \"$1\"; fi; }; "
        "clone_if_missing ComfyUI-LTXVideo https://github.com/Lightricks/ComfyUI-LTXVideo.git; "
        "clone_if_missing ComfyUI-GGUF https://github.com/city96/ComfyUI-GGUF.git; "
        "clone_if_missing ClownSampler_Beta_Standalone https://github.com/RiverSide71/ClownSampler_Beta_Standalone.git; "
        "clone_if_missing comfyui-workflow-to-api-converter-endpoint https://github.com/SethRobinson/comfyui-workflow-to-api-converter-endpoint.git; "
        "if [ -f ComfyUI-LTXVideo/requirements.txt ]; then python3 -m pip install -r ComfyUI-LTXVideo/requirements.txt; fi; "
        "if [ -f ComfyUI-GGUF/requirements.txt ]; then python3 -m pip install -r ComfyUI-GGUF/requirements.txt; fi; "
        "if curl -fsS http://127.0.0.1:8188/system_stats >/dev/null 2>&1; then "
        "pkill -f '[p]ython3 main.py.*--port 8188' || true; sleep 3; fi; "
        "cd \"$ROOT\"; nohup python3 main.py --listen 127.0.0.1 --port 8188 "
        "> /workspace/neo-comfyui.log 2>&1 < /dev/null & "
        "for i in $(seq 1 75); do "
        "if curl -fsS http://127.0.0.1:8188/system_stats >/dev/null 2>&1; then break; fi; sleep 2; done; "
        "curl -fsS http://127.0.0.1:8188/system_stats >/dev/null || "
        "{ tail -n 120 /workspace/neo-comfyui.log 2>/dev/null || true; exit 32; }; "
        "curl -fsS http://127.0.0.1:8188/object_info > /tmp/neo-object-info.json; "
        "python3 - <<'PY'\n"
        "import json\n"
        "d=json.load(open('/tmp/neo-object-info.json'))\n"
        "required=['UnetLoaderGGUF','LTXVAttentionBackend','DualCLIPLoader','LTXVTiledVAEDecode']\n"
        "missing=[x for x in required if x not in d]\n"
        "if missing: raise SystemExit('Missing ComfyUI nodes: '+', '.join(missing))\n"
        "print('Required GGUF/LTX nodes loaded')\n"
        "PY\n"
        "for name in 'ltx-2.3-22b-dev-Q4_0.gguf' 'ltx-2.3-22b-distilled-1.1_lora-dynamic_fro09_avg_rank_111_bf16.safetensors' 'gemma-3-12b-it-ablit-norms-biproj-fp8mixed.safetensors' 'ltx-2-3-22b-text_encoder.safetensors' 'LTX23_video_vae_bf16.safetensors' 'LTX23_audio_vae_bf16.safetensors'; do "
        "if ! find \"$ROOT/models\" -type f -name \"$name\" -print -quit | grep -q .; then "
        "echo \"Required cached model file missing: $name\"; exit 34; fi; done; "
        "echo 'ComfyUI API, required nodes and cached model files are ready'"
    )
    _remote(ssh_base, script, env, 360)


def _remote_logs(ssh_base: list[str] | None, env: dict[str, str]) -> str:
    if not ssh_base:
        return ""
    try:
        return _remote(ssh_base,
            "echo '=== ComfyUI ==='; tail -n 160 /workspace/neo-comfyui.log 2>/dev/null || true; "
            "echo '=== nvidia-smi ==='; nvidia-smi 2>&1 | tail -n 25 || true", env, 30)
    except Exception as exc:
        return "Could not collect remote logs: " + redact(str(exc))


def validate_api_workflow(path: Path, prompt_node_id: str, image_node_id: str | None, image_path: Path | None) -> str:
    if not path.is_file():
        raise FileNotFoundError("ComfyUI workflow JSON not found: " + str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise ValueError("Workflow must be a non-empty JSON object")
    if isinstance(data.get("nodes"), list) and isinstance(data.get("links"), list):
        nodes = {str(n.get("id")): n for n in data["nodes"] if isinstance(n, dict)}
        prompt_node = nodes.get(str(prompt_node_id))
        if not prompt_node or prompt_node.get("type") != "CLIPTextEncode":
            raise ValueError("Positive prompt node ID must identify a CLIPTextEncode node")
        if image_path:
            image_node = nodes.get(str(image_node_id or ""))
            if not image_node or image_node.get("type") != "LoadImage":
                raise ValueError("Image node ID must identify a LoadImage node")
        return json.dumps(data)
    for node in data.values():
        if not isinstance(node, dict) or not isinstance(node.get("class_type"), str) or not isinstance(node.get("inputs"), dict):
            raise ValueError("Workflow must be ComfyUI API format or ComfyUI editor format")
    if prompt_node_id not in data:
        raise ValueError("Prompt node ID is not present in the API workflow")
    if image_path and (not image_path.is_file() or not image_node_id or image_node_id not in data):
        raise ValueError("Valid start-image path and image-loader node ID are required for I2V")
    return json.dumps(data)


def _convert_ui_workflow(endpoint: str, workflow_json: str, prompt_node_id: str,
                         image_node_id: str | None, image_path: str | None) -> str:
    graph = json.loads(workflow_json)
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        return workflow_json
    # The upstream graph includes an optional LoadImage branch. Bypass that
    # node for pure T2V so no example.png asset is required on the rented host.
    for node in graph.get("nodes", []):
        if str(node.get("id")) == str(image_node_id or "2004") and node.get("type") == "LoadImage":
            node["mode"] = 0 if image_path else 4
    response = requests.post(endpoint.rstrip("/") + "/workflow/convert", json=graph, timeout=90)
    if not response.ok:
        raise RuntimeError("ComfyUI UI-to-API conversion failed (" + str(response.status_code) + "): " + redact(response.text[:1000]))
    api = response.json()
    if not isinstance(api, dict) or str(prompt_node_id) not in api:
        raise RuntimeError("Converted API workflow is missing positive prompt node " + str(prompt_node_id))
    inputs = api[str(prompt_node_id)].get("inputs", {})
    if not any(isinstance(v, str) and k.lower() in {"text", "prompt"} for k, v in inputs.items()):
        raise RuntimeError("Converted positive prompt node has no text input")
    if image_path:
        image_id = str(image_node_id or "")
        if image_id not in api or "image" not in api[image_id].get("inputs", {}):
            raise RuntimeError("Converted image loader has no image input")
    return json.dumps(api)


def run_ltx_inference(
    *, workflow_path: str, prompt: str, prompt_node_id: str, image_path: str | None = None,
    image_node_id: str | None = None, timeout_seconds: int = 600, require_audio: bool = True,
    budget_usd: float = MAX_BUDGET_USD, max_hourly_usd: float = MAX_HOURLY_USD,
    runtime_minutes: int = MAX_RUNTIME_MINUTES, min_vram_gb: float = MIN_GPU_VRAM_GB,
    disk_gb: int = DEFAULT_DISK_GB, model_download_gb: float = 0.0,
    output_upload_gb: float = 1.0, volume_hourly_usd: float = 0.0,
    volume_id: str | None = None, comfyui_root: str = "/workspace/ComfyUI",
    progress=print,
) -> str:
    if not prompt.strip():
        raise ValueError("Prompt cannot be empty")
    if not 0 < budget_usd <= MAX_BUDGET_USD:
        raise ValueError("Budget must be greater than zero and no more than $3")
    if not 0 < max_hourly_usd <= MAX_HOURLY_USD:
        raise ValueError("Hourly cap must be greater than zero and no more than $0.30")
    if not 0 < runtime_minutes <= MAX_RUNTIME_MINUTES:
        raise ValueError("Runtime must be greater than zero and no more than 18 minutes")
    if min_vram_gb < MIN_GPU_VRAM_GB:
        raise ValueError("LTX-2.3 GGUF 24GB path requires at least 24GB VRAM")
    if disk_gb < DEFAULT_DISK_GB or model_download_gb < 0 or output_upload_gb < 0 or volume_hourly_usd < 0:
        raise ValueError("Disk, bandwidth or volume pricing input is invalid")
    workflow = validate_api_workflow(
        Path(workflow_path), prompt_node_id, image_node_id,
        Path(image_path) if image_path else None)
    if not all(shutil.which(x) for x in ("ssh", "ssh-keygen", "vastai")):
        raise RuntimeError("ssh, ssh-keygen and Vast CLI must be installed on the runner")

    env = os.environ.copy()
    api = VastAPI(env.get("VAST_API_KEY", ""))
    start = time.monotonic()
    temp = Path(tempfile.mkdtemp(prefix="neo-ltx-vast-"))
    key_path = temp / "neo_ltx_inference_ed25519"
    known_hosts = temp / "known_hosts"
    instance_id = None
    selected = None
    ssh_base = None
    tunnel = None
    ssh_agent_started = False
    output_path = None
    failure = None
    cleanup_error = None
    remote_log = ""

    def log(message: str) -> None:
        if progress:
            progress("[" + time.strftime("%H:%M:%S UTC", time.gmtime()) + "] " + str(message))

    try:
        log("MODE: LTX-2.3 VIDEO INFERENCE ONLY. No model training.")
        log("GPU policy: verified/rentable on-demand full RTX GPU, 24GB+; Tesla excluded. RTX 3090/4090 preferred.")
        log("Caps: budget=$" + str(budget_usd) + ", hourly=$" + str(max_hourly_usd)
            + ", runtime=" + str(runtime_minutes) + " minutes.")
        _ssh_agent(env)
        ssh_agent_started = True
        _run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key_path)], env)
        public_key = Path(str(key_path) + ".pub").read_text(encoding="utf-8").strip()
        _run(["vastai", "create", "ssh-key", public_key], env)
        instance_id, selected = rent_with_refresh(
            api, volume_id=volume_id or env.get("VAST_VOLUME_ID"), progress=log,
            min_vram_gb=min_vram_gb, max_hourly_usd=max_hourly_usd,
            budget_usd=budget_usd, runtime_minutes=runtime_minutes, disk_gb=disk_gb,
            model_download_gb=model_download_gb, output_upload_gb=output_upload_gb,
            volume_hourly_usd=volume_hourly_usd,
        )
        log("Vast instance created: " + str(instance_id))
        deadline = time.monotonic() + runtime_minutes * 60
        _wait_running(api, instance_id, min(deadline, time.monotonic() + 12 * 60), log)

        ssh_deadline = min(deadline, time.monotonic() + 4 * 60)
        last_error = None
        while time.monotonic() < ssh_deadline:
            try:
                ssh_base = _ssh_base(instance_id, key_path, known_hosts, env)
                log("SSH and GPU verified: " + _gpu_check(ssh_base, env, min_vram_gb))
                break
            except Exception as exc:
                last_error = exc
                ssh_base = None
                log("SSH/GPU is not ready: " + redact(str(exc)))
                time.sleep(10)
        if ssh_base is None:
            raise TimeoutError("Vast reached running but SSH/nvidia-smi did not pass: " + str(last_error))

        log("Checking prepared ComfyUI; model training and automatic model downloads are disabled.")
        _start_comfyui(ssh_base, env, comfyui_root)
        tunnel_log = (temp / "ssh-tunnel.log").open("w", encoding="utf-8")
        tunnel = subprocess.Popen(
            ssh_base + ["-N", "-L", "8188:127.0.0.1:8188"],
            env=env, stdout=subprocess.DEVNULL, stderr=tunnel_log, text=True)
        endpoint = "http://127.0.0.1:8188"
        ready = False
        for _ in range(30):
            if tunnel.poll() is not None:
                raise RuntimeError("SSH tunnel stopped: " + (temp / "ssh-tunnel.log").read_text()[-1200:])
            try:
                response = requests.get(endpoint + "/system_stats", timeout=3)
                if response.ok:
                    ready = True
                    break
            except requests.RequestException:
                pass
            time.sleep(1)
        if not ready:
            raise TimeoutError("ComfyUI did not respond through the SSH tunnel")
        remaining = int(runtime_minutes * 60 - (time.monotonic() - start) - 45)
        if remaining < 60:
            raise TimeoutError("Less than 60 seconds remain inside the runtime cap")
        generation_timeout = min(timeout_seconds, remaining)
        log("Converting official LTX-2.3 editor graph to ComfyUI API prompt.")
        api_workflow = _convert_ui_workflow(endpoint, workflow, prompt_node_id, image_node_id, image_path)
        log("Submitting one ComfyUI job; timeout=" + str(generation_timeout) + "s.")
        output_path = generate_video(
            endpoint, api_workflow, prompt, prompt_node_id, image_path, image_node_id,
            generation_timeout, require_audio)
        log("Video generated: " + output_path)

    except Exception as exc:
        failure = exc
        log("INFERENCE FAILURE: " + redact(str(exc)))
        remote_log = _remote_logs(ssh_base, env)
        context = (
            "Inference only, not training. The prior NEO rental pattern uses filtered POST /bundles, "
            "PUT /asks, stale-offer refresh, ssh-agent, vastai ssh-url, nvidia-smi and destroy-finally. "
            "ComfyUI and compatible LTX-2.3 model files must already exist on the Vast image or attached "
            "volume. Limits: budget $" + str(budget_usd) + ", hourly $" + str(max_hourly_usd)
            + ", runtime " + str(runtime_minutes) + " min, min VRAM " + str(min_vram_gb)
            + "GB. Never advise training, Tesla, weakening filters or increasing spend.\n"
            + "Remote logs:\n" + remote_log
        )
        try:
            log("=== DeepSeek failure advisor ===")
            log(analyze_failure(str(exc), context))
        except Exception as advisor_error:
            log("DeepSeek advisor unavailable: " + redact(str(advisor_error)))
    finally:
        if tunnel is not None:
            tunnel.terminate()
            try:
                tunnel.wait(timeout=10)
            except subprocess.TimeoutExpired:
                tunnel.kill()
        if instance_id is not None:
            try:
                log("Destroying Vast instance " + str(instance_id))
                api.destroy(instance_id)
                log("Vast destroy request accepted.")
            except Exception as exc:
                cleanup_error = exc
                log("CRITICAL: manually destroy instance " + str(instance_id) + ": " + redact(str(exc)))
        if ssh_agent_started:
            subprocess.run(["ssh-agent", "-k"], env=env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=False)
        shutil.rmtree(temp, ignore_errors=True)

    info = {
        "mode": "ltx23_inference_only",
        "instance_id": instance_id,
        "offer_id": selected.offer_id if selected else None,
        "gpu_name": selected.gpu_name if selected else None,
        "gpu_vram_gb": selected.gpu_vram_gb if selected else None,
        "estimated_total_usd": selected.total_usd if selected else None,
        "budget_cap_usd": budget_usd, "hourly_cap_usd": max_hourly_usd,
        "runtime_cap_minutes": runtime_minutes, "elapsed_seconds": round(time.monotonic() - start, 2),
        "output_path": output_path, "failure": redact(str(failure)) if failure else None,
        "cleanup_failure": redact(str(cleanup_error)) if cleanup_error else None,
    }
    Path("outputs").mkdir(exist_ok=True)
    Path("outputs/vast_ltx_run_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    if cleanup_error:
        raise RuntimeError("Vast cleanup failed: " + str(cleanup_error)) from cleanup_error
    if failure:
        raise failure
    if not output_path:
        raise RuntimeError("Generation completed without a video output")
    return output_path
