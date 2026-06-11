from decimal import Decimal

import pytest
from pydantic import ValidationError

from packages.core.contracts import Money, ProviderInvocation, ProviderStatus, UsageMeterRecord, utcnow


def test_money_requires_iso_currency_and_preserves_decimal_micro_amount():
    money = Money(amount=Decimal("0.123456"), currency="CNY", amount_micro=123456)

    assert money.amount == Decimal("0.123456")
    assert money.amount_micro == 123456
    assert money.model_dump(mode="json") == {
        "amount": "0.123456",
        "currency": "CNY",
        "amount_micro": 123456,
    }

    with pytest.raises(ValidationError):
        Money(amount=Decimal("1"))
    with pytest.raises(ValidationError):
        Money(amount=Decimal("1"), currency="CN")


def test_usage_meter_record_uses_split_media_units_and_raw_usage():
    usage = UsageMeterRecord(
        id="usage_1",
        provider_invocation_id="pinv_1",
        provider_id="sandbox",
        model_id="tts.local",
        capability_id="tts.speech",
        input_tokens=10,
        output_tokens=3,
        cached_input_tokens=4,
        audio_seconds=Decimal("1.5"),
        video_seconds=Decimal("2.25"),
        image_count=1,
        provider_credits=Decimal("0.001"),
        raw_usage={"segments": [{"duration_sec": 1.5}]},
    )

    assert usage.cached_input_tokens == 4
    assert usage.audio_seconds == 1.5
    assert usage.video_seconds == 2.25
    assert usage.image_count == 1
    assert usage.provider_credits == Decimal("0.001")
    assert usage.raw_usage["segments"][0]["duration_sec"] == 1.5
    assert "media_seconds" not in usage.model_fields_set


def test_provider_invocation_tracks_usage_billing_and_external_timestamps():
    started_at = utcnow()
    usage = UsageMeterRecord(
        id="usage_1",
        provider_invocation_id="pinv_1",
        provider_id="sandbox",
        model_id="tts.local",
        capability_id="tts.speech",
        audio_seconds=Decimal("2"),
    )
    invocation = ProviderInvocation(
        id="pinv_1",
        provider_id="sandbox",
        model_id="tts.local",
        provider_profile_id="sandbox.tts.default",
        capability_id="tts.speech",
        status=ProviderStatus.succeeded,
        usage=usage,
        price_item_id="price_tts",
        billing_status="estimated",
        estimated_cost=Money(amount=Decimal("0.000002"), currency="CNY", amount_micro=2),
        external_job_id="job_external_1",
        started_at=started_at,
        finished_at=started_at,
    )

    assert invocation.usage is usage
    assert invocation.price_item_id == "price_tts"
    assert invocation.billing_status == "estimated"
    assert invocation.external_job_id == "job_external_1"
    assert invocation.started_at == started_at
    assert invocation.finished_at == started_at
