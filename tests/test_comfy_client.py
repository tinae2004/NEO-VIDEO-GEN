import json

import pytest

from neo_video_gen.comfy_client import generate_video


def test_rejects_missing_prompt_node():
    with pytest.raises(ValueError, match="Prompt node"):
        generate_video("http://localhost:8188", json.dumps({"1": {"inputs": {}}}), "hello", "9")


def test_rejects_missing_prompt_field():
    workflow = {"1": {"inputs": {"seed": 42}}}
    with pytest.raises(ValueError, match="no text"):
        generate_video("http://localhost:8188", json.dumps(workflow), "hello", "1")


def test_rejects_invalid_url():
    workflow = {"1": {"inputs": {"text": ""}}}
    with pytest.raises(ValueError, match="http"):
        generate_video("localhost:8188", json.dumps(workflow), "hello", "1")
