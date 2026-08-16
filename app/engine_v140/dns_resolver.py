from __future__ import annotations
import ipaddress,re,shutil,socket,subprocess
from dataclasses import dataclass
PUBLIC_DNS=("1.1.1.1","8.8.8.8")
@dataclass
class DNSResult:
    host:str; ips:list[str]; method:str; error:str|None=None

def _valid_ipv4(value:str)->bool:
    try:return isinstance(ipaddress.ip_address(value),ipaddress.IPv4Address)
    except Exception:return False

def system_resolve(host:str)->list[str]:
    ips=[]
    try:
        for item in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM):
            ip=item[4][0]
            if _valid_ipv4(ip) and ip not in ips:ips.append(ip)
    except Exception:pass
    return ips

def _parse_nslookup(text:str,host:str)->list[str]:
    ips=[]; low=text.lower(); pos=low.rfind("name:"); relevant=text[pos:] if pos>=0 else text
    for candidate in re.findall(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])",relevant):
        if _valid_ipv4(candidate) and candidate not in ips:ips.append(candidate)
    return ips

def nslookup_resolve(host:str,server:str)->list[str]:
    exe=shutil.which("nslookup")
    if not exe:return []
    try:
        cp=subprocess.run([exe,host,server],capture_output=True,text=True,timeout=8,encoding="utf-8",errors="replace")
        return _parse_nslookup((cp.stdout or "")+"\n"+(cp.stderr or ""),host)
    except Exception:return []

def resolve_host(host:str)->DNSResult:
    ips=system_resolve(host)
    if ips:return DNSResult(host,ips,"system")
    for server in PUBLIC_DNS:
        ips=nslookup_resolve(host,server)
        if ips:return DNSResult(host,ips,f"nslookup:{server}")
    return DNSResult(host,[],"failed",f"DNS-Auflösung für {host} fehlgeschlagen")
