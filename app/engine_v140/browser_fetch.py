from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse, parse_qs, urlunparse
from hashlib import sha256
import json
import os
import time
import socket
import re

import httpx

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
    diagnostics:dict=field(default_factory=dict)


class BrowserFetchError(RuntimeError):
    def __init__(self,message:str,diagnostics:dict|None=None):
        super().__init__(message)
        self.diagnostics=diagnostics or {}


_EDEKA_PAGE_HOSTS={"edeka.de","www.edeka.de"}
_SAFE_RESPONSE_HEADERS=(
    "content-type","content-length","server","via","x-cache","x-request-id",
    "cache-control","date","strict-transport-security","alt-svc",
)
_URL_IN_TEXT=re.compile(r"https?://[^\s\"'<>]+")


def _safe_response_headers(headers)->dict[str,str]:
    """Retain operational response evidence without cookies or credentials."""
    return {
        name:str(headers.get(name))[:1000]
        for name in _SAFE_RESPONSE_HEADERS
        if headers.get(name) is not None
    }


def _safe_diagnostic_url(url:str)->str:
    parsed=urlparse(url)
    hostname=(parsed.hostname or "").lower()
    netloc=hostname
    try:
        if parsed.port is not None:
            netloc=f"{hostname}:{parsed.port}"
    except ValueError:
        pass
    query=""
    if hostname in _EDEKA_PAGE_HOSTS:
        allowed=parse_qs(parsed.query).get("selectedMarktID",[])
        if allowed:
            query=urlencode({"selectedMarktID":allowed[0]})
    return urlunparse((parsed.scheme,netloc,parsed.path,parsed.params,query,""))


def _safe_error_text(value:object)->str:
    return _URL_IN_TEXT.sub(lambda match:_safe_diagnostic_url(match.group(0)),str(value))[:1000]


def _approved_edeka_navigation(url:str)->bool:
    parsed=urlparse(url)
    try:
        port=parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme=="https"
        and (parsed.hostname or "").lower() in _EDEKA_PAGE_HOSTS
        and parsed.username is None
        and parsed.password is None
        and port in (None,443)
    )


def _block_reason(response,body_prefix:str)->str|None:
    low=body_prefix.lower()
    if "access denied" in low or "you don't have permission to access" in low:
        return "akamai_access_denied" if (response.headers.get("server") or "").lower()=="akamaighost" else "access_denied"
    if "captcha" in low or "robot or human" in low:
        return "captcha"
    if response.status_code in {401,403,429}:
        return f"http_{response.status_code}"
    return None


def _http_attempt(response,request_url:str,dns_result,redirect_chain:list[str])->dict:
    body_prefix=response.text[:10000]
    return {
        "method":"GET",
        "request_url":_safe_diagnostic_url(request_url),
        "request_profile":"transparent_spareno_audit",
        "dns_method":dns_result.method,
        "dns_ips":list(dns_result.ips),
        "http_status":response.status_code,
        "http_version":response.http_version,
        "final_url":_safe_diagnostic_url(str(response.url)),
        "final_host":(response.url.host or "").lower(),
        "redirect_chain":[_safe_diagnostic_url(item) for item in redirect_chain],
        "response_headers":_safe_response_headers(response.headers),
        "content_type":response.headers.get("content-type",""),
        "response_bytes":len(response.content),
        "body_sha256":sha256(response.content).hexdigest(),
        "body_marker":_block_reason(response,body_prefix),
    }


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


def _edeka_http_first(url:str,timeout_ms:int,attempts:list[dict]|None=None)->BrowserFetchResult|None:
    """Read EDEKA's official server-rendered market offer surface without JS.

    The central ``/angebote/?selectedMarktID=...`` page is an official public
    EDEKA surface and already contains offer HTML.  Some datacenter Playwright
    traffic receives a CDN Access Denied page, so prefer a normal HTTP GET for
    this exact endpoint and keep Playwright as the existing fallback.
    """
    parsed=urlparse(url)
    host=(parsed.hostname or "").lower()
    query=parse_qs(parsed.query)
    central_landing = parsed.path.rstrip("/") == "/angebote" and bool(query.get("selectedMarktID"))
    market_detail = bool(re.fullmatch(r"/maerkte/\d+/angebote/?", parsed.path))
    if host not in _EDEKA_PAGE_HOSTS or not (central_landing or market_detail):
        return None
    evidence=attempts if attempts is not None else []
    dns_result=resolve_host(host)
    redirect_chain=[]
    request_url=url
    try:
        for _ in range(6):
            response=httpx.get(
                request_url,
                follow_redirects=False,
                timeout=max(timeout_ms/1000,1),
                headers={
                    # Be transparent.  The previously spoofed Chrome UA is
                    # reproducibly rejected by Akamai while this public GET is
                    # accepted without cookies or browser impersonation.
                    "User-Agent":"Spareno-Audit/1.0",
                    "Accept":"text/html",
                    "Accept-Language":"de-DE,de;q=0.9",
                },
            )
            if response.is_redirect:
                location=response.headers.get("location")
                target=urljoin(str(response.url),location or "")
                attempt=_http_attempt(response,request_url,dns_result,redirect_chain)
                attempt["redirect_target"]=_safe_diagnostic_url(target)
                evidence.append(attempt)
                if not _approved_edeka_navigation(target):
                    raise BrowserFetchError(
                        "EDEKA-Redirect zu nicht freigegebenem Host blockiert.",
                        {"fetch_attempts":list(evidence),"block_reason":"unapproved_redirect"},
                    )
                redirect_chain.append(target)
                request_url=target
                continue

            attempt=_http_attempt(response,request_url,dns_result,redirect_chain)
            evidence.append(attempt)
            if response.status_code in {401,403,429} or attempt["body_marker"]:
                return None
            response.raise_for_status()
            # Reject tiny/interstitial responses so Playwright can still try.
            if len(response.content)<5000:
                attempt["body_marker"]="unexpected_small_response"
                return None
            return BrowserFetchResult(
                response.content,
                response.headers.get("content-type","text/html; charset=utf-8"),
                str(response.url),
                "http-edeka-server-rendered",
                dns_result.method,
                diagnostics={
                    "fetch_attempts":list(evidence),
                    "http_status":response.status_code,
                    "http_version":response.http_version,
                    "response_headers":_safe_response_headers(response.headers),
                    "redirect_chain":[_safe_diagnostic_url(item) for item in redirect_chain],
                    "final_host":(response.url.host or "").lower(),
                    "block_reason":None,
                    "fallback_used":False,
                },
            )
        raise BrowserFetchError(
            "EDEKA-Redirect-Limit überschritten.",
            {"fetch_attempts":list(evidence),"block_reason":"redirect_limit"},
        )
    except (httpx.TimeoutException,httpx.HTTPError) as exc:
        evidence.append({
            "method":"GET","request_url":_safe_diagnostic_url(request_url),
            "request_profile":"transparent_spareno_audit",
            "dns_method":dns_result.method,"dns_ips":list(dns_result.ips),
            "final_host":(urlparse(request_url).hostname or "").lower(),
            "redirect_chain":[_safe_diagnostic_url(item) for item in redirect_chain],
            "error_type":type(exc).__name__,"error":_safe_error_text(exc),
            "body_marker":"network_or_http_error",
        })
        return None


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
    args=["--disable-dev-shm-usage","--no-sandbox"]
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
    navigation_attempt={
        "method":"GET","request_url":_safe_diagnostic_url(url),"request_profile":"playwright",
        "dns_method":dns_result.method,"dns_ips":list(dns_result.ips),
        "final_url":_safe_diagnostic_url(url),"final_host":host.lower(),"redirect_chain":[],
    }
    blocked_navigation=[]
    if host.lower() in _EDEKA_PAGE_HOSTS:
        def guard_edeka_navigation(route):
            request=route.request
            if request.is_navigation_request() and request.frame==page.main_frame:
                if not _approved_edeka_navigation(request.url):
                    blocked_navigation.append(_safe_diagnostic_url(request.url))
                    route.abort("blockedbyclient")
                    return
            route.continue_()
        page.route("**/*",guard_edeka_navigation)
    try:
        try:
            navigation_response=page.goto(url,wait_until="domcontentloaded",timeout=timeout_ms)
        except Exception as exc:
            if blocked_navigation:
                navigation_attempt["redirect_chain"]=blocked_navigation
                navigation_attempt["body_marker"]="unapproved_redirect"
                raise BrowserFetchError(
                    "EDEKA-Browsernavigation zu nicht freigegebenem Host blockiert.",
                    {"fetch_attempts":[navigation_attempt],"block_reason":"unapproved_redirect"},
                ) from exc
            raise
        if navigation_response is not None:
            navigation_attempt.update({
                "http_status":navigation_response.status,
                "final_url":_safe_diagnostic_url(navigation_response.url),
                "final_host":(urlparse(navigation_response.url).hostname or "").lower(),
                "response_headers":_safe_response_headers(navigation_response.headers),
                "content_type":navigation_response.headers.get("content-type",""),
            })
        try:
            page.wait_for_load_state("networkidle",timeout=12000)
        except Exception:
            page.wait_for_timeout(2500)

        body=(page.locator("body").inner_text(timeout=4000) or "")[:5000].lower()
        if "err_name_not_resolved" in body:
            navigation_attempt["body_marker"]="browser_dns_error"
            raise BrowserFetchError("Browser-DNS-Fehlerseite",{"fetch_attempts":[navigation_attempt],"block_reason":"browser_dns_error"})
        if "access denied" in body or "you don't have permission to access" in body:
            navigation_attempt["body_marker"]="access_denied"
            raise BrowserFetchError("CDN Access Denied",{"fetch_attempts":[navigation_attempt],"block_reason":"access_denied"})

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
            diagnostics={
                "fetch_attempts":[navigation_attempt],
                "http_status":navigation_attempt.get("http_status"),
                "response_headers":navigation_attempt.get("response_headers",{}),
                "redirect_chain":navigation_attempt.get("redirect_chain",[]),
                "final_host":(urlparse(final_url).hostname or "").lower(),
                "block_reason":None,
                "fallback_used":False,
            },
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
    attempts=[]
    direct=_edeka_http_first(url,timeout_ms,attempts=attempts)
    if direct is not None:
        return direct

    from playwright.sync_api import sync_playwright
    host=urlparse(url).hostname or ""
    dns_result=resolve_host(host)
    errors=[]
    with sync_playwright() as pw:
        for executable in _system_browser_candidates():
            try:
                profile=Path(__file__).resolve().parent.parent/"data"/"browser_profile"
                result=_capture_page(
                    pw,url,executable,"system-browser",timeout_ms,dns_result,
                    profile_dir=profile,capture_diagnostics=capture_diagnostics,
                    drain_offer_surface=drain_offer_surface,
                )
                result.diagnostics["fetch_attempts"]=[*attempts,*result.diagnostics.get("fetch_attempts",[])]
                result.diagnostics["fallback_used"]=bool(attempts)
                return result
            except Exception as exc:
                errors.append(f"system-browser:{Path(executable).name}: {exc}")
                if isinstance(exc,BrowserFetchError):
                    attempts.extend(exc.diagnostics.get("fetch_attempts",[]))
                else:
                    attempts.append({
                        "method":"GET","request_url":_safe_diagnostic_url(url),"request_profile":"system_browser",
                        "final_host":host.lower(),"error":_safe_error_text(exc),
                    })
        for attempt in range(1,3):
            try:
                result=_capture_page(
                    pw,url,None,f"playwright-{attempt}",timeout_ms,dns_result,
                    profile_dir=None,capture_diagnostics=capture_diagnostics,
                    drain_offer_surface=drain_offer_surface,
                )
                result.diagnostics["fetch_attempts"]=[*attempts,*result.diagnostics.get("fetch_attempts",[])]
                result.diagnostics["fallback_used"]=bool(attempts)
                return result
            except Exception as exc:
                errors.append(f"playwright-{attempt}: {exc}")
                if isinstance(exc,BrowserFetchError):
                    attempts.extend(exc.diagnostics.get("fetch_attempts",[]))
                else:
                    attempts.append({
                        "method":"GET","request_url":_safe_diagnostic_url(url),"request_profile":f"playwright_{attempt}",
                        "final_host":host.lower(),"error":_safe_error_text(exc),
                    })
                time.sleep(attempt)
    last=attempts[-1] if attempts else {}
    raise BrowserFetchError(
        f"Browser-Abruf fehlgeschlagen für {host}; DNS={dns_result.method} " + " | ".join(errors[-5:]),
        {
            "fetch_attempts":attempts,
            "http_status":last.get("http_status"),
            "response_headers":last.get("response_headers",{}),
            "redirect_chain":last.get("redirect_chain",[]),
            "final_host":last.get("final_host",host.lower()),
            "block_reason":last.get("body_marker") or last.get("error") or "all_fetch_paths_failed",
            "fallback_used":True,
        },
    )
