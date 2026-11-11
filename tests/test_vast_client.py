import json

import pytest

from neo_video_gen.vast_client import VastClient


def eligible_offer(**overrides):
    offer = {
        "id": 123,
        "gpu_name": "RTX_3090",
        "gpu_ram": 24576,
        "reliability": 0.995,
        "verification": "verified",
        "rentable": True,
        "num_gpus": 1,
        "disk_space": 200,
        "dph_base": 0.20,
        "dph_total": 0.22,
        "storage_cost": 0.10,
        "inet_down_cost": 0.001,
        "inet_up_cost": 0.002,
    }
    offer.update(overrides)
    return offer


def test_quote_accounts_for_compute_storage_and_bandwidth():
    quote = VastClient.quote_offer(eligible_offer())
    assert quote is not None
    assert quote.gpu_ram_gb == 24.0
    assert quote.estimated_total_usd > quote.compute_usd
    assert quote.estimated_total_usd < 3.0


@pytest.mark.parametrize(
    "overrides",
    [
        {"gpu_name": "Tesla_T4"},
        {"gpu_name": "RTX 3080"},
        {"verification": "deverified"},
        {"rentable": False},
        {"reliability": 0.90},
        {"gpu_ram": 16384},
        {"disk_space": 50},
        {"inet_down_cost": None},
    ],
)
def test_rejects_ineligible_or_unpriced_offer(overrides):
    assert VastClient.quote_offer(eligible_offer(**overrides)) is None


def test_normalizes_space_in_gpu_model_and_uses_vast_memory_units():
    quote = VastClient.quote_offer(eligible_offer(gpu_name="RTX 3090"))
    assert quote is not None
    assert quote.hourly_rate_usd == 0.22
    assert quote.gpu_ram_gb == 24.0


def test_budget_and_runtime_hard_limits():
    client = VastClient("test-key")
    with pytest.raises(ValueError, match="no more than"):
        client.affordable_quotes(budget_usd=3.01)
    with pytest.raises(ValueError, match="18 minutes"):
        client.affordable_quotes(runtime_minutes=19)


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"offers": [eligible_offer()]}


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.body = None
        self.url = None

    def post(self, url, json, timeout):
        self.url = url
        self.body = json
        return FakeResponse()


def test_search_uses_current_vast_post_bundles_contract():
    session = FakeSession()
    client = VastClient("test-key", session=session)
    offers = client.search_model("RTX_3090")
    assert offers[0]["id"] == 123
    assert session.url.endswith("/bundles")
    assert session.body["gpu_name"] == {"eq": "RTX_3090"}
    assert session.body["gpu_ram"] == {"gte": 24000}
    assert session.body["allocated_storage"] == 100
    assert session.body["type"] == "ondemand"
