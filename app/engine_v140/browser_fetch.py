from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
import json
import os
import time
import socket

from .dns_resolver import resolve_host

@dataclass
class BrowserFetchResult:
    content:bytes
    content_type:str
    final_url:str
    mode:str
    dns_method:str="unknown"
    console_errors:tuple[str,...]=()
    failed_requests:tuple[str,...]=()
    screenshot_png:bytes|None=None


def _resolve_host(hostname:str)->list[str]:
    """Compatibility helper retained for older tests/callers."""
    ips=[]
    try:
        for item in socket.getaddrinfo(hostname,443,type=socket.SOCK_STREAM):
            ip=item[4][0]
            if ":" not in ip and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    return ips

def _system_browser_candidates()->list[str]:
    candidates=[]
    env=os.environ
    paths=[
        Path(env.get("PROGRAMFILES(X86)",""))/"Microsoft/Edge/Application/msedge.exe",
        Path(env.get("PROGRAMFILES",""))/"Microsoft/Edge/Application/msedge.exe",
        Path(env.get("LOCALAPPDATA",""))/"Microsoft/Edge/Application/msedge.exe",
        Path(env.get("PROGRAMFILES",""))/"Google/Chrome/Application/chrome.exe",
        Path(env.get("PROGRAMFILES(X86)",""))/"Google/Chrome/Application/chrome.exe",
        Path(env.get("LOCALAPPDATA",""))/"Google/Chrome/Application/chrome.exe",
    ]
    for p in paths:
        try:
            if str(p) and p.exists() and str(p) not in candidates:
                candidates.append(str(p))
        except Exception:
            pass
    return candidates

def _load_complete_surface(page,max_iterations:int=20)->None:
    """Drain bounded load-more/infinite-scroll surfaces until the DOM is stable."""
    labels=(
        "Alle Angebote ansehen","Alle anzeigen","Zu den Angeboten","Angebote anzeigen",
        "Mehr Angebote","Weitere Angebote","Mehr laden","Mehr anzeigen",
    )
    previous_signature=None
    stable_iterations=0
    for _ in range(max_iterations):
        for label in labels:
            try:
                matches=page.get_by_text(label,exact=True)
                for idx in range(min(matches.count(),4)):
                    element=matches.nth(idx)
                    if element.is_visible() and element.is_enabled():
                        element.click(timeout=1200)
                        page.wait_for_timeout(350)
                        break
            except Exception:
                pass
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(500)
            signature=page.evaluate("""() => ({
              height: document.body.scrollHeight,
              offers: document.querySelectorAll(
                'article, [data-testid*="offer" i], [class*="offer-card" i], [id^="angebot-"]'
              ).length
            })""")
        except Exception:
            return
        if signature==previous_signature:
            stable_iterations+=1
        else:
            stable_iterations=0
            previous_signature=signature
        if stable_iterations>=2:
            break
    try:
        page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass


def _legacy_surface_pass(page)->None:
    """Preserve the pre-audit browser behavior for existing collectors."""
    for label in (
        "Alle Angebote ansehen","Alle anzeigen","Zu den Angeboten","Angebote anzeigen",
        "Mehr Angebote","Weitere Angebote",
    ):
        try:
            loc=page.get_by_text(label,exact=True)
            for idx in range(min(loc.count(),4)):
                el=loc.nth(idx)
                if el.is_visible():
                    try:
                        el.click(timeout=1200)
                        page.wait_for_timeout(700)
                    except Exception:
                        pass
        except Exception:
            pass
    try:
        page.evaluate("""async () => {
          for (let y=0; y<document.body.scrollHeight; y+=900) {
            window.scrollTo(0,y); await new Promise(r=>setTimeout(r,100));
          }
          window.scrollTo(0,0);
        }""")
        page.wait_for_timeout(900)
    except Exception:
        pass


def _capture_page(
    playwright,url:str,executable_path:str|None,mode:str,timeout_ms:int,dns_result,
    profile_dir:Path|None=None,capture_diagnostics:bool=False,drain_offer_surface:bool=False,
):
    host=urlparse(url).hostname or ""
    rules=[]
    if dns_result.ips:
        rules.append(f"MAP {host} {dns_result.ips[0]}")
    if host.startswith("www."):
        bare=host[4:]
        bare_result=resolve_host(bare)
        if bare_result.ips:
            rules.append(f"MAP {bare} {bare_result.ips[0]}")
    args=["--disable-dev-shm-usage","--no-sandbox","--disable-blink-features=AutomationControlled"]
    if rules:
        args.append("--host-resolver-rules="+", ".join(rules))

    network_payloads=[]
    console_errors=[]
    failed_requests=[]

    def attach(page):
        if capture_diagnostics:
            page.on("console", lambda message: console_errors.append(message.text[:1000]) if message.type == "error" and len(console_errors) < 100 else None)
            page.on("requestfailed", lambda request: failed_requests.append(f"{request.method} {request.url} :: {request.failure}") if len(failed_requests) < 100 else None)
        def _capture_response(response):
            try:
                ctype=(response.headers.get("content-type") or "").lower()
                url_low=response.url.lower()
                if "json" not in ctype and not any(k in url_low for k in ("offer","angebot","product","produkt","market","filial","prospekt")):
                    return
                if len(network_payloads)>=100:
                    return
                data=response.json()
                raw=json.dumps(data,ensure_ascii=False,default=str)
                if len(raw)>900_000:
                    return
                low=raw.lower()
                if any(k in low for k in ("price","preis","offer","angebot","product","produkt","gtin","ean")):
                    network_payloads.append({"url":response.url,"data":data})
            except Exception:
                pass
        page.on("response",_capture_response)

    context=None
    browser=None
    if profile_dir is not None:
        profile_dir.mkdir(parents=True,exist_ok=True)
        context=playwright.chromium.launch_persistent_context(
            str(profile_dir), executable_path=executable_path, headless=True,
            args=args, locale="de-DE", timezone_id="Europe/Berlin",
            viewport={"width":1440,"height":1100},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        )
        page=context.pages[0] if context.pages else context.new_page()
    else:
        browser=playwright.chromium.launch(headless=True,executable_path=executable_path,args=args)
        context=browser.new_context(
            locale="de-DE",timezone_id="Europe/Berlin", viewport={"width":1440,"height":1100},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
            extra_http_headers={"Accept-Language":"de-DE,de;q=0.9,en;q=0.7","DNT":"1"},
        )
        page=context.new_page()

    attach(page)
    try:
        page.goto(url,wait_until="domcontentloaded",timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle",timeout=12000)
        except Exception:
            page.wait_for_timeout(2500)

        body=(page.locator("body").inner_text(timeout=4000) or "")[:5000].lower()
        if "err_name_not_resolved" in body:
            raise RuntimeError("Browser-DNS-Fehlerseite")
        if "access denied" in body or "you don't have permission to access" in body:
            raise RuntimeError("CDN Access Denied")

        for label in ("Alle akzeptieren","Akzeptieren","Zustimmen","Einverstanden","Alle Cookies akzeptieren","Auswahl bestätigen"):
            try:
                b=page.get_by_role("button",name=label,exact=False)
                if b.count():
                    b.first.click(timeout=900)
                    page.wait_for_timeout(500)
                    break
            except Exception:
                pass

        if drain_offer_surface:
            _load_complete_surface(page)
        else:
            _legacy_surface_pass(page)

        page_html=page.content()
        final_url=page.url
        network_json=json.dumps(network_payloads,ensure_ascii=False,default=str)
        injected='<script id="lpc-network-json" type="application/json">'+network_json.replace("</script>","<\\/script>")+'</script>'
        if "</body>" in page_html:
            page_html=page_html.replace("</body>",injected+"</body>",1)
        else:
            page_html+=injected
        screenshot_png=None
        if capture_diagnostics:
            try:
                screenshot_png=page.screenshot(full_page=True,type="png")
            except Exception as exc:
                console_errors.append(f"screenshot_failed: {exc}")
        return BrowserFetchResult(
            page_html.encode("utf-8"),"text/html; charset=utf-8",final_url,mode,dns_result.method,
            tuple(console_errors),tuple(failed_requests),screenshot_png,
        )
    finally:
        try: context.close()
        except Exception: pass
        try:
            if browser: browser.close()
        except Exception: pass


def browser_fetch(
    url:str,timeout_ms:int=45000,capture_diagnostics:bool=False,drain_offer_surface:bool=False,
)->BrowserFetchResult:
    from playwright.sync_api import sync_playwright
    host=urlparse(url).hostname or ""
    dns_result=resolve_host(host)
    errors=[]
    with sync_playwright() as pw:
        for executable in _system_browser_candidates():
            try:
                profile=Path(__file__).resolve().parent.parent/"data"/"browser_profile"
                return _capture_page(
                    pw,url,executable,"system-browser",timeout_ms,dns_result,
                    profile_dir=profile,capture_diagnostics=capture_diagnostics,
                    drain_offer_surface=drain_offer_surface,
                )
            except Exception as exc:
                errors.append(f"system-browser:{Path(executable).name}: {exc}")
        for attempt in range(1,3):
            try:
                return _capture_page(
                    pw,url,None,f"playwright-{attempt}",timeout_ms,dns_result,
                    profile_dir=None,capture_diagnostics=capture_diagnostics,
                    drain_offer_surface=drain_offer_surface,
                )
            except Exception as exc:
                errors.append(f"playwright-{attempt}: {exc}")
                time.sleep(attempt)
    raise RuntimeError(f"Browser-Abruf fehlgeschlagen für {host}; DNS={dns_result.method} " + " | ".join(errors[-5:]))