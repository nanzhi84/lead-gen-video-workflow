"""XiaoVmaoPublishAdapter (CDP 驱动小V猫) unit tests.

These exercise adapter selection, the 4-platform constant guard, and — with a
mocked CDP driver (no live 小V猫 / no real accounts) — the **honest failure**
contract: the adapter may drive 小V猫's publish form, but until real submit +
success detection lands (PR5) it must NEVER fabricate a published result.
"""

from __future__ import annotations

import asyncio

import pytest

from packages.core import contracts as c
from packages.core.contracts import PlatformAccount
from packages.publishing.connectors import xiaovmao_cdp as cdp
from packages.publishing.platform_adapter import (
    XIAOVMAO_ADAPTER_ID,
    XIAOVMAO_PLATFORM_KEY_MAP,
    XIAOVMAO_PLATFORM_NAME_MAP,
    PublishPayload,
    XiaoVmaoPublishAdapter,
    select_adapter,
)

_LOGGED_IN = PlatformAccount(uid="acct-douyin", platform="douyin", is_login=True)


def _install_fake_cdp(monkeypatch, *, accounts, fill_ok=True, connect_error=None):
    """Patch the CDP connector with a fake driver + account reader. Returns a
    ``recorded`` dict capturing the file-input + evaluate calls _drive_publish makes."""
    recorded: dict = {"files": None, "evals": 0, "connected": False, "closed": False}

    class FakeDriver:
        def __init__(self, *, host, port):
            self.host, self.port = host, port

        async def connect(self, timeout_seconds: int = 30):
            if connect_error is not None:
                raise connect_error
            recorded["connected"] = True

        async def close(self):
            recorded["closed"] = True

        async def set_files_by_index(self, selector, index, files):
            recorded["files"] = (selector, index, tuple(files))

        async def evaluate(self, expression, await_promise: bool = False):
            recorded["evals"] += 1
            return {"ok": fill_ok}

    async def fake_read(driver):
        return list(accounts)

    monkeypatch.setattr(cdp, "XiaoVmaoDriver", FakeDriver)
    monkeypatch.setattr(cdp, "_read_accounts", fake_read)
    return recorded


def test_select_xiaovmao_adapter(monkeypatch):
    monkeypatch.setenv("CUTAGENT_PUBLISH_ADAPTER", "xiaovmao.cdp")
    adapter = select_adapter()
    assert isinstance(adapter, XiaoVmaoPublishAdapter)
    assert adapter.adapter_id == XIAOVMAO_ADAPTER_ID == "xiaovmao.cdp"


def test_xiaovmao_platform_maps_cover_four_platforms_no_bilibili():
    four = {"douyin", "kuaishou", "shipinhao", "xiaohongshu"}
    assert set(XIAOVMAO_PLATFORM_KEY_MAP) == four
    assert set(XIAOVMAO_PLATFORM_NAME_MAP) == four
    assert "bilibili" not in XIAOVMAO_PLATFORM_KEY_MAP


def test_publish_unavailable_returns_honest_failure(monkeypatch):
    # 小V猫不可达（connect 抛错）→ 显式失败，绝不伪造成功。
    _install_fake_cdp(
        monkeypatch,
        accounts=[_LOGGED_IN],
        connect_error=cdp.XiaoVmaoUnavailableError("小V猫未运行"),
    )
    outcome = XiaoVmaoPublishAdapter().publish(
        PublishPayload(title="t", platforms=("douyin",), video_uri="/v.mp4")
    )
    assert outcome.success is False
    assert outcome.adapter_id == "xiaovmao.cdp"
    assert outcome.error_message


def test_probe_accounts_unavailable_returns_reason(monkeypatch):
    _install_fake_cdp(
        monkeypatch,
        accounts=[],
        connect_error=cdp.XiaoVmaoUnavailableError("小V猫未运行"),
    )
    accounts, available, reason = XiaoVmaoPublishAdapter().probe_accounts()
    assert accounts == []
    assert available is False
    assert reason


def test_publish_drives_form_but_never_fabricates_success(monkeypatch):
    # 账号匹配 + 表单填充成功，但提交+成功检测未实现（待 PR5）→ 必须诚实失败，
    # 绝不因为"填了表单"就伪造发布成功。
    recorded = _install_fake_cdp(monkeypatch, accounts=[_LOGGED_IN], fill_ok=True)
    outcome = XiaoVmaoPublishAdapter().publish(
        PublishPayload(
            title="标题",
            description="正文",
            platforms=("douyin",),
            tags=("话题a",),
            video_uri="/local/finished.mp4",
        )
    )
    # 表单确实被驱动了（成片注入 + 至少填了一次文本）
    assert recorded["files"] == ("input[type=file]", 0, ("/local/finished.mp4",))
    assert recorded["evals"] >= 1
    # 但绝不伪造成功
    assert outcome.success is False
    assert "未真正发布" in (outcome.error_message or "")


def test_publish_fails_when_video_missing(monkeypatch):
    # 账号已登录但缺成片 → 诚实失败，且不会上传任何文件。
    recorded = _install_fake_cdp(monkeypatch, accounts=[_LOGGED_IN])
    outcome = XiaoVmaoPublishAdapter().publish(PublishPayload(title="t", platforms=("douyin",)))
    assert outcome.success is False
    assert outcome.error_message
    assert recorded["files"] is None


def test_publish_fails_when_dom_fill_lost(monkeypatch):
    # 表单填充返回 {ok: false}（选择器变更）→ 诚实失败，不伪造成功。
    _install_fake_cdp(monkeypatch, accounts=[_LOGGED_IN], fill_ok=False)
    outcome = XiaoVmaoPublishAdapter().publish(
        PublishPayload(title="t", platforms=("douyin",), video_uri="/v.mp4")
    )
    assert outcome.success is False
    assert outcome.error_message


def test_publish_fails_when_no_logged_in_account(monkeypatch):
    recorded = _install_fake_cdp(
        monkeypatch,
        accounts=[PlatformAccount(uid="a", platform="douyin", is_login=False)],
    )
    outcome = XiaoVmaoPublishAdapter().publish(
        PublishPayload(title="t", platforms=("douyin",), video_uri="/v.mp4")
    )
    assert outcome.success is False
    assert outcome.error_message
    assert recorded["files"] is None


def test_publish_fails_targeted_account_without_xiaovmao_uid(monkeypatch):
    recorded = _install_fake_cdp(monkeypatch, accounts=[_LOGGED_IN])
    outcome = XiaoVmaoPublishAdapter().publish(
        PublishPayload(
            title="t",
            platforms=("douyin",),
            video_uri="/v.mp4",
            account_id="acct_1",
            account_name="dy",
        )
    )

    assert outcome.success is False
    assert "xiaovmao_uid" in (outcome.error_message or "")
    assert recorded["files"] is None


def test_cdp_send_timeout_fails_loudly():
    class TimeoutWebSocket:
        async def send(self, _payload):
            return None

        async def recv(self):
            raise asyncio.TimeoutError

    driver = cdp.XiaoVmaoDriver()
    driver.websocket = TimeoutWebSocket()

    with pytest.raises(cdp.XiaoVmaoUnavailableError, match="Runtime.evaluate"):
        asyncio.run(driver.send("Runtime.evaluate"))


class _FakeLoginPage:
    def __init__(self, *evaluate_results):
        self.evaluate_results = list(evaluate_results)
        self.sent: list[tuple[str, dict]] = []

    async def evaluate(self, expression, await_promise: bool = False):
        return self.evaluate_results.pop(0)

    async def send(self, method, params=None):
        self.sent.append((method, params or {}))
        return {"result": {}}


def test_login_driver_extracts_data_url_qr_image():
    page = _FakeLoginPage({"qr_image": "data:image/png;base64,qr", "expired": False})
    driver = cdp.XiaoVmaoLoginDriver()

    qr = asyncio.run(driver.capture_qr_image(page))

    assert qr == "data:image/png;base64,qr"
    assert page.sent == []


def test_login_driver_refreshes_expired_qr_by_clicking_center():
    page = _FakeLoginPage(
        {
            "qr_image": None,
            "expired": True,
            "qr_rect": {"x": 10, "y": 20, "width": 120, "height": 120},
        },
        {"qr_image": "data:image/png;base64,fresh", "expired": False},
    )
    driver = cdp.XiaoVmaoLoginDriver()

    qr = asyncio.run(driver.capture_qr_image(page))

    assert qr == "data:image/png;base64,fresh"
    assert [call[0] for call in page.sent] == [
        "Input.dispatchMouseEvent",
        "Input.dispatchMouseEvent",
    ]
    assert page.sent[0][1]["x"] == 70
    assert page.sent[0][1]["y"] == 80


def test_login_driver_emits_verifying_status_for_second_factor():
    page = _FakeLoginPage({"detail": "抖音身份验证，请完成短信验证码"})
    driver = cdp.XiaoVmaoLoginDriver()
    events: list[c.LoginStreamEvent] = []

    asyncio.run(driver.emit_verification_if_needed(page, events.append))

    assert events == [
        c.LoginStreamEvent(
            type="status",
            status="verifying",
            detail="抖音身份验证，请完成短信验证码",
        )
    ]


def test_login_driver_detects_completed_logged_in_account(monkeypatch):
    async def fake_read_accounts(_driver):
        return [
            PlatformAccount(uid="old", platform="douyin", nickname="old", is_login=True),
            PlatformAccount(uid="new", platform="douyin", nickname="new", is_login=True),
        ]

    monkeypatch.setattr(cdp, "_read_accounts", fake_read_accounts)
    driver = cdp.XiaoVmaoLoginDriver()

    account = asyncio.run(
        driver.find_completed_account(object(), platform="douyin", known_uids={"old"})
    )

    assert account is not None
    assert account.uid == "new"


def test_login_manager_emits_error_event_on_driver_exception():
    class FailingLoginDriver:
        async def run_login(self, **kwargs):
            raise cdp.XiaoVmaoUnavailableError("小V猫不可达")

    manager = cdp.XiaoVmaoLoginManager(driver_factory=lambda: FailingLoginDriver())
    account = c.PublishAccount(
        id="acct_1",
        client_id="client_1",
        platform="douyin",
        account_name="dy",
    )

    manager.begin("login_1", account, on_account=lambda _platform_account: account)
    events: list[c.LoginStreamEvent] = []
    for _ in range(4):
        event = manager.next_event("login_1", timeout=1)
        if event is not None:
            events.append(event)
        if manager.poll("login_1").status == "failed":
            break

    assert manager.poll("login_1").status == "failed"
    assert any(event.type == "error" and "小V猫不可达" in (event.detail or "") for event in events)
