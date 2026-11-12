from neo_video_gen.vast_inference import eligible_offers, quote_offer


def offer(**overrides):
    item = {
        "id": 1001,
        "gpu_name": "RTX A6000",
        "gpu_ram": 48000,
        "reliability": 0.999,
        "dph_total": 0.25,
        "disk_space": 200,
        "num_gpus": 1,
        "gpu_frac": 1.0,
        "verified": True,
        "rentable": True,
        "inet_down_cost": 0.001,
        "inet_up_cost": 0.001,
    }
    item.update(overrides)
    return item


def test_accepts_full_verified_rentable_48gb_rtx_offer():
    result = quote_offer(offer(), model_download_gb=0.0)
    assert result is not None
    assert result.offer_id == 1001
    assert result.gpu_vram_gb == 48.0


def test_rejects_24gb_rtx_3090_for_ltx23_default_path():
    assert quote_offer(offer(gpu_name="RTX 3090", gpu_ram=24000), model_download_gb=0.0) is None


def test_rejects_tesla():
    assert quote_offer(offer(gpu_name="Tesla V100"), model_download_gb=0.0) is None


def test_rejects_fractional_or_unrentable_gpu():
    assert quote_offer(offer(gpu_frac=0.5), model_download_gb=0.0) is None
    assert quote_offer(offer(rentable=False), model_download_gb=0.0) is None


def test_rejects_hourly_price_over_cap():
    assert quote_offer(offer(dph_total=0.31), model_download_gb=0.0) is None


def test_download_bandwidth_is_included_in_total_budget():
    assert quote_offer(offer(inet_down_cost=0.1), model_download_gb=55.0) is None


def test_filter_returns_only_safe_rtx_offers():
    quotes = eligible_offers(
        [
            offer(id=1, gpu_name="RTX A6000"),
            offer(id=2, gpu_name="RTX 3090", gpu_ram=24000),
            offer(id=3, gpu_name="Tesla A100"),
        ],
        model_download_gb=0.0,
    )
    assert [quote.offer_id for quote in quotes] == [1]
