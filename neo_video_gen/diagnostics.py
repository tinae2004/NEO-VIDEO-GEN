"""DeepSeek failure advisor. Advisory only; it never controls infrastructure."""
from __future__ import annotations
import os
import re
from typing import Any
import requests

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"

def redact(value: str) -> str:
    value = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._-]+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)(hf[_-]?token\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]", value)
    value = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED]", value)
    return value[-12000:]

def analyze_failure(error: str, context: str = "") -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return "DeepSeek advisor skipped: DEEPSEEK_API_KEY is not configured."
    system = (
        "You are the diagnostic engineer for NEO VIDEO GEN's LTX-2.3 inference "
        "and Vast.ai provisioning pipeline. Analyze only supplied logs and context. "
        "Identify the failing stage, root cause, evidence, and smallest safe fix. "
        "Separate proven facts from hypotheses. Never request or reveal secrets. "
        "Never recommend exceeding the USD budget, hourly cap, runtime cap, minimum "
        "VRAM, or using Tesla GPUs. You are advisory only: you cannot run commands, "
        "edit files, rent GPUs, restart jobs, or destroy instances. Keep under 350 words."
    )
    user = "Inference workflow failure:\n" + redact(error)
    if context:
        user += "\n\nRelevant redacted context:\n" + redact(context)
    response = requests.post(
        API_URL,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0.1,
            "max_tokens": 700,
        },
        timeout=40,
    )
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    return payload["choices"][0]["message"]["content"].strip()
