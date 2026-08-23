from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1] / "frontend-lovable-source" / "src"
DIRECT_API_FETCH = re.compile(r"\bfetch\s*\(\s*([`\"])/api/")


def test_frontend_api_calls_use_device_aware_client():
    offenders = []
    for path in ROOT.rglob("*"):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        if path.name == "api-client.ts":
            continue
        text = path.read_text(encoding="utf-8")
        if DIRECT_API_FETCH.search(text):
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == [], (
        "Direct /api fetch() calls bypass stable device identity. "
        "Use apiFetch() instead: " + ", ".join(offenders)
    )
