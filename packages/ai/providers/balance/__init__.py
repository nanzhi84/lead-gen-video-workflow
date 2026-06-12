from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import re

import httpx

from packages.core.contracts import Money, ProviderBalanceItem, ProviderProfile, utcnow
from packages.core.storage.secret_store import SecretStore

_SECRET_RE = re.compile(r"Bearer\s+\S+|sk-[A-Za-z0-9_\-]+|LTAI[A-Za-z0-9]+", re.IGNORECASE)


def _detail(text: str, secret: str | None = None) -> str:
    value = _SECRET_RE.sub("***", text)
    if secret:
        value = value.replace(secret, "***")
    return value[:240]


def _item(
    profile: ProviderProfile,
    *,
    status: str,
    checked_at: datetime,
    balance: Money | None = None,
    quota_remaining: float | None = None,
    unit: str | None = None,
    detail: str | None = None,
) -> ProviderBalanceItem:
    return ProviderBalanceItem(
        provider_id=profile.provider_id,
        account_group=profile.id,
        balance=balance,
        quota_remaining=quota_remaining,
        unit=unit,
        checked_at=checked_at,
        status=status,
        detail=detail,
    )


def _money(value: object, currency: object = "CNY") -> Money:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        amount = Decimal("0")
    code = str(currency or "CNY").upper()
    if len(code) != 3:
        code = "CNY"
    return Money(amount=amount, currency=code)


def _secret_for(profile: ProviderProfile, secret_store: SecretStore) -> str | None:
    return secret_store.get(profile.secret_ref) if profile.secret_ref else None


def _base_url(profile: ProviderProfile, default: str) -> str:
    options = profile.default_options or {}
    value = options.get("base_url") if isinstance(options, Mapping) else None
    return str(value or default).rstrip("/")


def _json_response(response: httpx.Response, secret: str) -> dict:
    if response.status_code in {401, 403}:
        raise PermissionError("unauthorized")
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {}


def _deepseek(profile: ProviderProfile, secret: str, client: httpx.Client, checked_at: datetime) -> ProviderBalanceItem:
    try:
        response = client.get(
            f"{_base_url(profile, 'https://api.deepseek.com')}/user/balance",
            headers={"Authorization": f"Bearer {secret}"},
        )
        data = _json_response(response, secret)
        infos = data.get("balance_infos") or []
        chosen = next((item for item in infos if item.get("currency") == "CNY"), infos[0] if infos else None)
        if not chosen:
            return _item(profile, status="error", checked_at=checked_at, detail="响应缺少 balance_infos")
        return _item(
            profile,
            status="ok",
            checked_at=checked_at,
            balance=_money(chosen.get("total_balance"), chosen.get("currency")),
        )
    except PermissionError:
        return _item(profile, status="unauthorized", checked_at=checked_at, detail="鉴权失败")
    except Exception as exc:
        return _item(profile, status="error", checked_at=checked_at, detail=_detail(f"余额查询失败: {exc}", secret))


def _kimi(profile: ProviderProfile, secret: str, client: httpx.Client, checked_at: datetime) -> ProviderBalanceItem:
    try:
        response = client.get(
            f"{_base_url(profile, 'https://api.moonshot.cn/v1')}/users/me/balance",
            headers={"Authorization": f"Bearer {secret}"},
        )
        data = _json_response(response, secret)
        if data.get("code") != 0:
            return _item(profile, status="error", checked_at=checked_at, detail=f"接口返回 code={data.get('code')}")
        balance = (data.get("data") or {}).get("available_balance")
        if balance is None:
            return _item(profile, status="error", checked_at=checked_at, detail="响应缺少 available_balance")
        return _item(profile, status="ok", checked_at=checked_at, balance=_money(balance, "CNY"))
    except PermissionError:
        return _item(profile, status="unauthorized", checked_at=checked_at, detail="鉴权失败")
    except Exception as exc:
        return _item(profile, status="error", checked_at=checked_at, detail=_detail(f"余额查询失败: {exc}", secret))


def _runninghub(
    profile: ProviderProfile,
    secret: str,
    client: httpx.Client,
    checked_at: datetime,
) -> ProviderBalanceItem:
    try:
        response = client.post(
            f"{_base_url(profile, 'https://www.runninghub.ai')}/uc/openapi/accountStatus",
            json={"apikey": secret},
            headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
        )
        data = _json_response(response, secret)
        if data.get("code") != 0:
            return _item(profile, status="error", checked_at=checked_at, detail=f"接口返回 code={data.get('code')}")
        payload = data.get("data") or {}
        coins = payload.get("remainCoins")
        if coins is None:
            return _item(profile, status="error", checked_at=checked_at, detail="响应缺少 remainCoins")
        balance = _money(payload.get("remainMoney"), "CNY") if payload.get("remainMoney") is not None else None
        return _item(
            profile,
            status="ok",
            checked_at=checked_at,
            balance=balance,
            quota_remaining=float(coins),
            unit="coins",
        )
    except PermissionError:
        return _item(profile, status="unauthorized", checked_at=checked_at, detail="鉴权失败")
    except Exception as exc:
        return _item(profile, status="error", checked_at=checked_at, detail=_detail(f"余额查询失败: {exc}", secret))


def _openai(profile: ProviderProfile, secret: str, client: httpx.Client, checked_at: datetime) -> ProviderBalanceItem:
    root = _base_url(profile, "https://api.openai.com")
    root = root[:-3].rstrip("/") if root.endswith("/v1") else root
    today = checked_at.date()
    params = {
        "start_date": (today - timedelta(days=99)).isoformat(),
        "end_date": (today + timedelta(days=1)).isoformat(),
    }
    try:
        headers = {"Authorization": f"Bearer {secret}"}
        subscription = _json_response(client.get(f"{root}/v1/dashboard/billing/subscription", headers=headers), secret)
        usage = _json_response(client.get(f"{root}/v1/dashboard/billing/usage", headers=headers, params=params), secret)
        hard_limit = subscription.get("hard_limit_usd")
        total_usage = usage.get("total_usage")
        if hard_limit is None or total_usage is None:
            return _item(profile, status="error", checked_at=checked_at, detail="响应缺少 hard_limit_usd/total_usage")
        used = Decimal(str(total_usage)) / Decimal("100")
        remaining = Decimal(str(hard_limit)) - used
        return _item(profile, status="ok", checked_at=checked_at, balance=Money(amount=remaining, currency="USD"))
    except PermissionError:
        return _item(profile, status="unauthorized", checked_at=checked_at, detail="鉴权失败")
    except Exception as exc:
        return _item(profile, status="error", checked_at=checked_at, detail=_detail(f"余额查询失败: {exc}", secret))


def query_provider_balance(
    profile: ProviderProfile,
    *,
    secret_store: SecretStore,
    http_client: httpx.Client,
    checked_at: datetime | None = None,
) -> ProviderBalanceItem:
    checked = checked_at or utcnow()
    provider_id = profile.provider_id.lower()
    if provider_id.startswith("minimax"):
        return _item(profile, status="unsupported", checked_at=checked, detail="MiniMax 暂无余额查询 API")
    secret = _secret_for(profile, secret_store)
    if not secret:
        return _item(profile, status="unconfigured", checked_at=checked, detail="未配置或无法读取 provider secret")
    if provider_id.startswith("deepseek"):
        return _deepseek(profile, secret, http_client, checked)
    if provider_id.startswith("kimi") or provider_id.startswith("moonshot"):
        return _kimi(profile, secret, http_client, checked)
    if provider_id.startswith("runninghub"):
        return _runninghub(profile, secret, http_client, checked)
    if provider_id.startswith("openai"):
        return _openai(profile, secret, http_client, checked)
    if provider_id.startswith("dashscope"):
        return _item(profile, status="unsupported", checked_at=checked, detail="DashScope 余额需阿里云 BSS 账户级查询")
    return _item(profile, status="unsupported", checked_at=checked, detail="该 provider 未接入余额查询")
