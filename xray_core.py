# xray_core.py
import json
import subprocess
import sys
import time
from pathlib import Path

# --- تنظیمات مسیر جدید ---
# فایل‌های Xray را داخل پوشه core قرار می‌دهیم
XRAY_DIR = Path(__file__).parent / "core"
XRAY_DIR.mkdir(exist_ok=True)  # اگر پوشه وجود نداشت، خودکار می‌سازد

XRAY_EXE = XRAY_DIR / "xray.exe"
CONFIG_PATH = XRAY_DIR / "config.json"
LOG_PATH = XRAY_DIR / "xray.log"

SOCKS_PORT = 10808
HTTP_PORT = 10809
API_PORT = 10811


def kill_zombie_xray():
    """کشتن پروسه‌های xray که از قبل باز مانده‌اند تا پورت‌ها آزاد شوند."""
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "xray.exe"],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            time.sleep(0.5)
        except Exception:
            pass


def _build_stream_settings(cfg: dict) -> dict:
    net = cfg.get("network", "tcp")
    security = (cfg.get("security") or "none").lower()
    host_header = cfg.get("host") or cfg.get("sni") or cfg["address"]

    stream = {"network": net}

    if net == "ws":
        stream["wsSettings"] = {
            "path": cfg.get("path", "/"),
            "headers": {"Host": host_header},
        }
    elif net == "grpc":
        stream["grpcSettings"] = {
            "serviceName": cfg.get("path", "").lstrip("/") or ""
        }
    elif net == "h2":
        stream["httpSettings"] = {
            "path": cfg.get("path", "/"),
            "host": [host_header],
        }

    if security == "tls":
        stream["security"] = "tls"
        stream["tlsSettings"] = {
            "serverName": cfg.get("sni") or host_header,
            "allowInsecure": False,
            "fingerprint": cfg.get("fp") or "chrome",
        }
    elif security == "reality":
        stream["security"] = "reality"
        stream["realitySettings"] = {
            "serverName": cfg.get("sni", ""),
            "fingerprint": cfg.get("fp") or "chrome",
            "publicKey": cfg.get("pbk", ""),
            "shortId": cfg.get("sid", ""),
            "spiderX": "/",
        }

    return stream


def _build_outbound(cfg: dict) -> dict:
    t = cfg["type"]

    if t == "vmess":
        return {
            "protocol": "vmess",
            "settings": {
                "vnext": [{
                    "address": cfg["address"],
                    "port": cfg["port"],
                    "users": [{
                        "id": cfg["uuid"],
                        "alterId": cfg.get("alterId", 0),
                        "security": cfg.get("cipher", "auto"),
                    }],
                }]
            },
            "streamSettings": _build_stream_settings(cfg),
        }

    if t == "vless":
        user = {"id": cfg["uuid"], "encryption": "none"}
        if cfg.get("flow"):
            user["flow"] = cfg["flow"]
        return {
            "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": cfg["address"],
                    "port": cfg["port"],
                    "users": [user],
                }]
            },
            "streamSettings": _build_stream_settings(cfg),
        }

    if t == "trojan":
        return {
            "protocol": "trojan",
            "settings": {
                "servers": [{
                    "address": cfg["address"],
                    "port": cfg["port"],
                    "password": cfg["password"],
                }]
            },
            "streamSettings": _build_stream_settings(cfg),
        }

    if t == "ss":
        return {
            "protocol": "shadowsocks",
            "settings": {
                "servers": [{
                    "address": cfg["address"],
                    "port": cfg["port"],
                    "method": cfg["method"],
                    "password": cfg["password"],
                }]
            },
            "streamSettings": {"network": "tcp"},
        }

    raise ValueError(f"پروتکل پشتیبانی نمی‌شود: {t}")


def build_full_config(cfg: dict,
                      socks_port: int = SOCKS_PORT,
                      http_port: int = HTTP_PORT,
                      api_port: int = API_PORT) -> dict:
    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "socks-in",
                "listen": "127.0.0.1",
                "port": socks_port,
                "protocol": "socks",
                "settings": {"udp": True, "auth": "noauth"},
            },
            {
                "tag": "http-in",
                "listen": "127.0.0.1",
                "port": http_port,
                "protocol": "http",
            }
        ],
        "outbounds": [
            _build_outbound(cfg),
            {"protocol": "freedom", "tag": "direct"},
            {"protocol": "blackhole", "tag": "block"},
        ]
    }

    # اگر پورت API صفر نبود، بخش استتس و API را اضافه کن
    if api_port:
        config["stats"] = {}
        config["api"] = {"tag": "api", "services": ["StatsService"]}
        config["policy"] = {"system": {"statsInboundUplink": True, "statsInboundDownlink": True}}
        config["inbounds"].append({
            "tag": "api",
            "listen": "127.0.0.1",
            "port": api_port,
            "protocol": "dokodemo-door",
            "settings": {"address": "127.0.0.1"},
        })
        config["routing"] = {
            "rules": [
                {"type": "field", "inboundTag": ["api"], "outboundTag": "api"},
            ]
        }

    return config


def start_xray(config: dict, config_path: Path = CONFIG_PATH) -> subprocess.Popen:
    if not XRAY_EXE.exists():
        raise FileNotFoundError(f"xray.exe پیدا نشد در مسیر: {XRAY_EXE}")

    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) \
        if sys.platform == "win32" else 0

    log_file = open(LOG_PATH, "w", encoding="utf-8")

    # اجرای xray با cwd تنظیم شده روی پوشه core
    proc = subprocess.Popen(
        [str(XRAY_EXE), "run", "-c", config_path.name],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
        cwd=str(XRAY_DIR)  # <--- این خط باعث می‌شود xray فایل‌های geoip و wintun را پیدا کند
    )
    proc._log_file = log_file  # type: ignore[attr-defined]
    return proc


def read_log_tail(n: int = 1500) -> str:
    try:
        return LOG_PATH.read_text(encoding="utf-8", errors="ignore")[-n:]
    except Exception:
        return ""