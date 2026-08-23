from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DetectedDevice:
    device_type: str
    os_name: str
    os_version: str | None
    browser_name: str
    browser_version: str | None


def _version(pattern: str, ua: str) -> str | None:
    match = re.search(pattern, ua, re.I)
    return match.group(1).replace("_", ".") if match else None


def detect_device(user_agent: str, *, mobile_hint: bool = False, platform: str = "", touch_points: int = 0) -> DetectedDevice:
    """Return coarse device/OS/browser information for product analytics.

    Client hints are preferred where available, while the user-agent parser
    covers Safari/iOS and older browsers. The result intentionally stays coarse
    and does not attempt hardware fingerprinting.
    """
    ua = user_agent or ""
    platform_text = (platform or "").lower()

    # iPadOS 13+ may identify itself as Macintosh; touch support distinguishes
    # it from a Mac without relying on an unstable hardware model string.
    is_ipad = "ipad" in ua.lower() or ("macintosh" in ua.lower() and touch_points > 1)
    is_iphone = "iphone" in ua.lower() or "ipod" in ua.lower()
    is_android = "android" in ua.lower()

    if is_iphone or is_ipad:
        os_name = "iOS" if is_iphone else "iPadOS"
        os_version = _version(r"OS ([0-9_]+)", ua)
    elif is_android:
        os_name = "Android"
        os_version = _version(r"Android\s+([0-9.]+)", ua)
    elif "windows" in ua.lower() or "win" in platform_text:
        os_name = "Windows"
        os_version = None
    elif "mac os x" in ua.lower() or "mac" in platform_text:
        os_name = "macOS"
        os_version = _version(r"Mac OS X\s+([0-9_]+)", ua)
    elif "cros" in ua.lower():
        os_name = "ChromeOS"
        os_version = None
    elif "linux" in ua.lower() or "linux" in platform_text:
        os_name = "Linux"
        os_version = None
    else:
        os_name = "Unknown"
        os_version = None

    lower = ua.lower()
    if "edg/" in lower:
        browser_name = "Edge"
        browser_version = _version(r"Edg/([0-9.]+)", ua)
    elif "opr/" in lower or "opera" in lower:
        browser_name = "Opera"
        browser_version = _version(r"(?:OPR|Opera)/([0-9.]+)", ua)
    elif "crios/" in lower:
        browser_name = "Chrome"
        browser_version = _version(r"CriOS/([0-9.]+)", ua)
    elif "fxios/" in lower:
        browser_name = "Firefox"
        browser_version = _version(r"FxiOS/([0-9.]+)", ua)
    elif "chrome/" in lower and "chromium" not in lower:
        browser_name = "Chrome"
        browser_version = _version(r"Chrome/([0-9.]+)", ua)
    elif "firefox/" in lower:
        browser_name = "Firefox"
        browser_version = _version(r"Firefox/([0-9.]+)", ua)
    elif "safari/" in lower and "version/" in lower:
        browser_name = "Safari"
        browser_version = _version(r"Version/([0-9.]+)", ua)
    else:
        browser_name = "Unknown"
        browser_version = None

    if is_ipad or "tablet" in lower:
        device_type = "tablet"
    elif is_iphone or is_android and (mobile_hint or "mobile" in lower):
        device_type = "mobile"
    elif mobile_hint:
        device_type = "mobile"
    else:
        device_type = "desktop"

    return DetectedDevice(
        device_type=device_type,
        os_name=os_name,
        os_version=os_version,
        browser_name=browser_name,
        browser_version=browser_version,
    )
