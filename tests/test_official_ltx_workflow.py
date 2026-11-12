import json
from pathlib import Path


def test_official_ltx23_distilled_workflow_structure():
    path = Path(__file__).resolve().parents[1] / "workflows" / "ltx23_distilled_ui.json"
    graph = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(graph.get("nodes"), list) and graph["nodes"]
    nodes = {str(node["id"]): node for node in graph["nodes"]}
    assert nodes["2483"]["type"] == "CLIPTextEncode"
    assert "Positive Prompt" in nodes["2483"].get("title", "")
    assert nodes["2004"]["type"] == "LoadImage"
    assert any(n["type"] == "CreateVideo" for n in graph["nodes"])
    assert any(n["type"] == "SaveVideo" for n in graph["nodes"])
    assert any(n["type"] == "LTXVAudioVAELoader" for n in graph["nodes"])
    assert any(n["type"] == "ClownSampler_Beta" for n in graph["nodes"])


def test_official_ltx23_workflow_model_assets_are_explicit():
    path = Path(__file__).resolve().parents[1] / "workflows" / "ltx23_distilled_ui.json"
    graph = json.loads(path.read_text(encoding="utf-8"))
    values = [str(v) for n in graph["nodes"] for v in (n.get("widgets_values") or [])]
    all_values = "\n".join(values)
    assert "ltx-2.3-22b-dev.safetensors" in all_values
    assert "ltx-2.3-22b-distilled-lora-384-1.1.safetensors" in all_values
    assert "comfy_gemma_3_12B_it.safetensors" in all_values
