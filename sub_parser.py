# parser.py
import base64
import json
from urllib.parse import urlparse, parse_qs, unquote


def b64_decode_safe(s: str) -> bytes:
    s = s.strip().replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s)


def decode_subscription(text: str) -> str:
    """اگر محتوا Base64 باشد دیکد می‌کند، وگرنه همان متن را برمی‌گرداند."""
    text = text.strip()
    if "://" in text:
        return text
    try:
        decoded = b64_decode_safe(text).decode("utf-8", errors="ignore")
        if "://" in decoded:
            return decoded
    except Exception:
        pass
    return text


def parse_vmess(uri: str) -> dict:
    payload = uri[len("vmess://"):]
    data = json.loads(b64_decode_safe(payload).decode("utf-8"))
    return {
        "type": "vmess",
        "name": data.get("ps") or "vmess",
        "address": data["add"],
        "port": int(data["port"]),
        "uuid": data["id"],
        "alterId": int(data.get("aid", 0) or 0),
        "cipher": data.get("scy", "auto") or "auto",
        "network": data.get("net", "tcp") or "tcp",
        "security": data.get("tls", "") or "none",
        "sni": data.get("sni", "") or data.get("host", ""),
        "host": data.get("host", ""),
        "path": data.get("path", "/") or "/",
        "fp": data.get("fp", ""),
        "pbk": "",
        "sid": "",
        "flow": "",
    }


def parse_vless(uri: str) -> dict:
    u = urlparse(uri)
    qs = parse_qs(u.query)
    return {
        "type": "vless",
        "name": unquote(u.fragment) or "vless",
        "address": u.hostname,
        "port": int(u.port),
        "uuid": unquote(u.username or ""),
        "network": qs.get("type", ["tcp"])[0],
        "security": qs.get("security", ["none"])[0],
        "sni": qs.get("sni", [""])[0] or qs.get("host", [""])[0],
        "host": qs.get("host", [""])[0],
        "path": unquote(qs.get("path", ["/"])[0]),
        "fp": qs.get("fp", [""])[0],
        "pbk": qs.get("pbk", [""])[0],
        "sid": qs.get("sid", [""])[0],
        "flow": qs.get("flow", [""])[0],
    }


def parse_trojan(uri: str) -> dict:
    u = urlparse(uri)
    qs = parse_qs(u.query)
    return {
        "type": "trojan",
        "name": unquote(u.fragment) or "trojan",
        "address": u.hostname,
        "port": int(u.port),
        "password": unquote(u.username or ""),
        "network": qs.get("type", ["tcp"])[0],
        "security": qs.get("security", ["tls"])[0],
        "sni": qs.get("sni", [""])[0] or qs.get("host", [""])[0],
        "host": qs.get("host", [""])[0],
        "path": unquote(qs.get("path", ["/"])[0]),
        "fp": qs.get("fp", [""])[0],
        "pbk": "",
        "sid": "",
        "flow": "",
    }


def parse_ss(uri: str) -> dict:
    body = uri[len("ss://"):]
    name = ""
    if "#" in body:
        body, name = body.split("#", 1)
        name = unquote(name)

    if "@" in body:
        method_pw, hostport = body.split("@", 1)
        if ":" not in method_pw:
            method_pw = b64_decode_safe(method_pw).decode()
    else:
        decoded = b64_decode_safe(body.split("?")[0]).decode()
        method_pw, hostport = decoded.split("@", 1)

    method, password = method_pw.split(":", 1)
    hostport = hostport.split("?")[0].split("/")[0]
    host, port = hostport.rsplit(":", 1)

    return {
        "type": "ss",
        "name": name or "ss",
        "address": host,
        "port": int(port),
        "method": method,
        "password": password,
    }


def parse_uri(uri: str):
    uri = uri.strip()
    if uri.startswith("vmess://"):
        return parse_vmess(uri)
    if uri.startswith("vless://"):
        return parse_vless(uri)
    if uri.startswith("trojan://"):
        return parse_trojan(uri)
    if uri.startswith("ss://"):
        return parse_ss(uri)
    return None


def parse_subscription(text: str) -> list:
    text = decode_subscription(text)
    configs = []
    for line in text.splitlines():
        line = line.strip()
        if not line or "://" not in line:
            continue
        try:
            cfg = parse_uri(line)
            if cfg:
                configs.append(cfg)
        except Exception as e:
            print(f"[parser] skip: {line[:40]}... ({e})")
    return configs