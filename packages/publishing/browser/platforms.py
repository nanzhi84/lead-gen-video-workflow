"""Per-platform login + creator-backend endpoints for the Playwright driver.

UNVERIFIED: these URLs/selectors are best-effort starting points for the Mac-Mini
Playwright driver and are NOT validated against the live platforms; they will need
tuning on real 抖音/视频号/快手/小红书 accounts and re-checking on each platform redesign.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformLogin:
    platform: str
    login_url: str
    creator_home_url: str
    qr_selector: str  # element to screenshot for the login QR
    logged_in_signal: str  # URL substring indicating a logged-in creator session


PLATFORM_LOGINS: dict[str, PlatformLogin] = {
    "douyin": PlatformLogin(
        platform="douyin",
        login_url="https://creator.douyin.com/",
        creator_home_url="https://creator.douyin.com/creator-micro/home",
        qr_selector="img[class*='qrcode'], canvas",
        logged_in_signal="creator-micro/home",
    ),
    "kuaishou": PlatformLogin(
        platform="kuaishou",
        login_url="https://cp.kuaishou.com/",
        creator_home_url="https://cp.kuaishou.com/article/manage/video",
        qr_selector="img[class*='qrcode'], canvas",
        logged_in_signal="article/manage",
    ),
    "shipinhao": PlatformLogin(
        platform="shipinhao",
        login_url="https://channels.weixin.qq.com/platform",
        creator_home_url="https://channels.weixin.qq.com/platform/home",
        qr_selector="img[class*='qrcode'], iframe",
        logged_in_signal="platform/home",
    ),
    "xiaohongshu": PlatformLogin(
        platform="xiaohongshu",
        login_url="https://creator.xiaohongshu.com/login",
        creator_home_url="https://creator.xiaohongshu.com/new/home",
        qr_selector="img[class*='qrcode'], canvas",
        logged_in_signal="new/home",
    ),
}


def platform_login(platform: str) -> PlatformLogin:
    login = PLATFORM_LOGINS.get(platform)
    if login is None:
        raise KeyError(platform)
    return login
