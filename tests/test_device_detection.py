from app.device_detection import detect_device


def test_detects_iphone_safari_as_mobile_ios():
    ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 Version/18.6 Mobile/15E148 Safari/604.1"
    result = detect_device(ua, mobile_hint=True, platform="iPhone", touch_points=5)
    assert result.device_type == "mobile"
    assert result.os_name == "iOS"
    assert result.os_version == "18.6"
    assert result.browser_name == "Safari"


def test_detects_android_chrome_as_mobile():
    ua = "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/140.0.0.0 Mobile Safari/537.36"
    result = detect_device(ua, mobile_hint=True, platform="Android", touch_points=5)
    assert result.device_type == "mobile"
    assert result.os_name == "Android"
    assert result.os_version == "15"
    assert result.browser_name == "Chrome"


def test_detects_windows_firefox_as_desktop():
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:154.0) Gecko/20100101 Firefox/154.0"
    result = detect_device(ua, platform="Win32")
    assert result.device_type == "desktop"
    assert result.os_name == "Windows"
    assert result.browser_name == "Firefox"
    assert result.browser_version == "154.0"


def test_ipados_desktop_user_agent_uses_touch_points():
    ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"
    result = detect_device(ua, platform="MacIntel", touch_points=5)
    assert result.device_type == "tablet"
    assert result.os_name == "iPadOS"
