"""Account-level grouping for provider balance reports.

Some provider ids are capability-level invocation adapters, while their balance is
settled at a shared cloud-account level. Keep that grouping explicit so the
dashboard does not show the same account balance once per capability profile.
"""

from __future__ import annotations

from collections.abc import Iterable

from packages.core.contracts import ProviderBalanceItem, ProviderProfile

_ALIYUN_PROVIDER_ID = "aliyun.billing"
_VOLCENGINE_PROVIDER_ID = "volcengine.billing"

_ACCOUNT_FAMILIES = (
    {
        "provider_id": _ALIYUN_PROVIDER_ID,
        "account_group": "aliyun.shared",
        "prefixes": ("aliyun", "dashscope", "qwen", "bailian"),
    },
    {
        "provider_id": _VOLCENGINE_PROVIDER_ID,
        "account_group": "volcengine.shared",
        "prefixes": ("volcengine", "volc", "ark"),
    },
)

_STATUS_RANK = {
    "ok": 0,
    "pending": 10,
    "unconfigured": 20,
    "unauthorized": 30,
    "error": 40,
    "unsupported": 50,
}


def _is_sandbox_provider_id(provider_id: str) -> bool:
    value = provider_id.lower()
    return value == "sandbox" or value.startswith("sandbox.") or value.startswith("sandbox-")


def _matches_prefix(provider_id: str, prefix: str) -> bool:
    value = provider_id.lower()
    return value == prefix or value.startswith(f"{prefix}.")


def canonical_balance_provider_id(provider_id: str) -> str:
    """Return the account-level provider id used for balance display."""

    for family in _ACCOUNT_FAMILIES:
        if any(_matches_prefix(provider_id, prefix) for prefix in family["prefixes"]):
            return family["provider_id"]
    return provider_id


def canonical_balance_account_group(provider_id: str) -> str | None:
    """Return the display account group for shared provider-account balances."""

    canonical = canonical_balance_provider_id(provider_id)
    for family in _ACCOUNT_FAMILIES:
        if canonical == family["provider_id"]:
            return family["account_group"]
    return None


def normalize_balance_item(item: ProviderBalanceItem) -> ProviderBalanceItem:
    """Project a balance item onto the account-level supplier shown in the UI."""

    provider_id = canonical_balance_provider_id(item.provider_id)
    shared_account_group = canonical_balance_account_group(item.provider_id)
    account_group = shared_account_group or item.account_group
    if (
        shared_account_group is None
        and account_group is not None
        and item.status in {"unsupported", "unconfigured"}
        and not _has_balance_value(item)
    ):
        account_group = None
    if provider_id == item.provider_id and account_group == item.account_group:
        return item
    return item.model_copy(update={"provider_id": provider_id, "account_group": account_group})


def _has_balance_value(item: ProviderBalanceItem) -> bool:
    return item.balance is not None or item.quota_remaining is not None


def _is_better_balance_item(candidate: ProviderBalanceItem, current: ProviderBalanceItem) -> bool:
    candidate_rank = (
        _STATUS_RANK.get(candidate.status, 99),
        0 if _has_balance_value(candidate) else 1,
    )
    current_rank = (_STATUS_RANK.get(current.status, 99), 0 if _has_balance_value(current) else 1)
    if candidate_rank != current_rank:
        return candidate_rank < current_rank
    return candidate.checked_at > current.checked_at


def coalesce_balance_items(items: Iterable[ProviderBalanceItem]) -> list[ProviderBalanceItem]:
    """Collapse capability-level duplicates into one account-level balance row.

    Items that map to the same shared cloud account (e.g. ``dashscope.llm`` and
    ``aliyun.billing`` both settle on the Aliyun account) are de-duplicated to a
    single representative row -- the best-status snapshot carrying a balance value
    (see ``_is_better_balance_item``). Balances are intentionally **NOT summed**:
    every duplicate reports the *same* account-level balance, so summing would
    double-count. Sandbox providers are dropped (no real vendor balance).
    """

    grouped: dict[tuple[str, str], ProviderBalanceItem] = {}
    for item in items:
        normalized = normalize_balance_item(item)
        if _is_sandbox_provider_id(normalized.provider_id):
            continue
        key = (normalized.provider_id, normalized.account_group or "default")
        current = grouped.get(key)
        if current is None or _is_better_balance_item(normalized, current):
            grouped[key] = normalized
    return sorted(grouped.values(), key=lambda item: (item.provider_id, item.account_group or ""))


def _profile_priority(profile: ProviderProfile, canonical_provider_id: str) -> tuple[int, str]:
    if profile.provider_id == canonical_provider_id and profile.capability == "balance.monitor":
        return (0, profile.id)
    if profile.provider_id == canonical_provider_id:
        return (1, profile.id)
    if profile.capability == "balance.monitor":
        return (2, profile.id)
    if profile.secret_ref:
        return (3, profile.id)
    return (4, profile.id)


def select_balance_query_profiles(profiles: Iterable[ProviderProfile]) -> list[ProviderProfile]:
    """Choose one balance-query profile per shared account family.

    Invocation profiles such as ``dashscope.llm`` and ``volcengine.seedance`` point
    at product APIs, but their balance is account-level. Prefer the dedicated
    ``*.billing`` monitor profile when it exists, then fall back to the best
    available family member.
    """

    selected_by_family: dict[str, ProviderProfile] = {}
    passthrough: list[ProviderProfile] = []
    for profile in profiles:
        if _is_sandbox_provider_id(profile.provider_id) or _is_sandbox_provider_id(profile.id):
            continue
        canonical = canonical_balance_provider_id(profile.provider_id)
        shared_group = canonical_balance_account_group(profile.provider_id)
        if shared_group is None:
            passthrough.append(profile)
            continue
        current = selected_by_family.get(canonical)
        if current is None or _profile_priority(profile, canonical) < _profile_priority(
            current, canonical
        ):
            selected_by_family[canonical] = profile
    return [*passthrough, *sorted(selected_by_family.values(), key=lambda profile: profile.id)]
