# ping_test.py
import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from PyQt5.QtCore import QThread, pyqtSignal

from xray_core import XRAY_EXE, XRAY_DIR, build_full_config

TEST_SITES = [
    {"name": "Google", "url": "https://www.gstatic.com/generate_204", "expected": [200, 204]},
    {"name": "Instagram", "url": "https://www.instagram.com/robots.txt", "expected": [200]},
    {"name": "X (Twitter)", "url": "https://x.com/robots.txt", "expected": [200]},
    {"name": "YouTube", "url": "https://www.youtube.com/generate_204", "expected": [200, 204]},
    {"name": "GitHub", "url": "https://github.com/robots.txt", "expected": [200]},
    {"name": "Gmail", "url": "https://mail.google.com/robots.txt", "expected": [200]},
    {"name": "Telegram", "url": "https://telegram.org/robots.txt", "expected": [200]},
    {"name": "WhatsApp", "url": "https://www.whatsapp.com/robots.txt", "expected": [200]},
    {"name": "Netflix", "url": "https://www.netflix.com/robots.txt", "expected": [200]},
    {"name": "Cloudflare", "url": "http://cp.cloudflare.com/generate_204", "expected": [200, 204]},
]

# افزایش تایم‌اوت‌ها برای جلوگیری از خطاهای الکی
TCP_TIMEOUT = 4.0
HTTP_TIMEOUT = 12.0
PORT_WAIT = 15.0
PORT_POLL = 0.1

# کاهش تعداد ورکرها برای جلوگیری از فریز شدن و بلاک شدن سرور
WORKERS = 4

_port_lock = threading.Lock()
_used_ports: set[int] = set()


def _find_free_port() -> int:
    with _port_lock:
        for _ in range(200):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]
            finally:
                s.close()
            if port not in _used_ports:
                _used_ports.add(port)
                return port
        raise RuntimeError("no free port")


def tcp_ping(host: str, port: int, timeout: float = TCP_TIMEOUT):
    # دو بار تلاش میکنیم تا اگر بار اول پکت گم شد، تست بی‌خودی خراب نشود
    for _ in range(2):
        try:
            t0 = time.time()
            with socket.create_connection((host, int(port)), timeout=timeout):
                return int((time.time() - t0) * 1000)
        except Exception:
            time.sleep(0.5)
    return None


def _wait_port(port: int, proc, timeout: float = PORT_WAIT) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(PORT_POLL)
    return False


def _try_url(site: dict, proxies: dict, timeout: float):
    name = site["name"]
    url = site["url"]
    expected = site["expected"]
    try:
        start = time.time()
        # allow_redirects=True برای سایت‌هایی مثل X.com که ریدایرکت میشن
        r = requests.get(url, proxies=proxies, timeout=timeout, allow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code in expected:
            return {"name": name, "ms": int((time.time() - start) * 1000), "err": None}
        return {"name": name, "ms": None, "err": f"HTTP {r.status_code}"}
    except requests.exceptions.Timeout:
        return {"name": name, "ms": None, "err": "timeout"}
    except requests.exceptions.SSLError:
        return {"name": name, "ms": None, "err": "ssl err"}
    except requests.exceptions.ConnectionError:
        return {"name": name, "ms": None, "err": "blocked"}
    except Exception:
        return {"name": name, "ms": None, "err": "failed"}


def _make_failed_details(err_msg: str):
    return [{"name": site["name"], "ms": None, "err": err_msg} for site in TEST_SITES]


def http_test_through_tunnel(cfg: dict, timeout: float = HTTP_TIMEOUT):
    if not XRAY_EXE.exists():
        return None, _make_failed_details("no xray.exe"), "no xray.exe"

    http_port = _find_free_port()
    socks_port = _find_free_port()
    try:
        config = build_full_config(cfg, socks_port=socks_port, http_port=http_port, api_port=0)
    except Exception as e:
        return None, _make_failed_details("config err"), f"config: {str(e)[:30]}"

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    tmp.write(json.dumps(config, indent=2))
    tmp.close()
    cfg_path = tmp.name

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    proc = None
    try:
        proc = subprocess.Popen(
            [str(XRAY_EXE), "run", "-c", cfg_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            cwd=str(XRAY_DIR)
        )

        if not _wait_port(http_port, proc, timeout=PORT_WAIT):
            return None, _make_failed_details("core failed"), "xray core failed to start"

        # مکث کوتاه برای اینکه Xray کاملاً آماده شود
        time.sleep(0.8)

        proxies = {"http": f"http://127.0.0.1:{http_port}", "https": f"http://127.0.0.1:{http_port}"}

        # درخواست پیش‌گرم برای اطمینان از برقراری کامل تونل
        try:
            requests.get("http://cp.cloudflare.com/generate_204", proxies=proxies, timeout=3)
        except Exception:
            pass

        results = []
        best_ms = None
        last_err = "all failed"

        # محدود کردن به 2 درخواست همزمان برای جلوگیری از بلاک شدن سرور
        with ThreadPoolExecutor(max_workers=2) as pool:
            futs = {pool.submit(_try_url, site, proxies, timeout): site for site in TEST_SITES}
            for fut in as_completed(futs):
                res = fut.result()
                results.append(res)
                if res.get("ms") is not None:
                    if best_ms is None or res["ms"] < best_ms:
                        best_ms = res["ms"]
                else:
                    last_err = res.get("err", "unknown")

        results.sort(key=lambda x: x["name"])

        if best_ms is not None:
            return best_ms, results, None
        return None, results, last_err

    finally:
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(1)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        try:
            Path(cfg_path).unlink(missing_ok=True)
        except Exception:
            pass


def test_server(cfg: dict):
    tcp_ms = tcp_ping(cfg["address"], cfg["port"])
    if tcp_ms is None:
        return {"kind": "fail", "ms": None, "reason": "TCP unreachable", "details": _make_failed_details("TCP fail")}

    http_ms, details, err = http_test_through_tunnel(cfg)
    if http_ms is not None:
        return {"kind": "http", "ms": http_ms, "reason": "ok", "details": details}

    return {"kind": "tcp", "ms": tcp_ms, "reason": err or "tunnel failed", "details": details}


class TestOneThread(QThread):
    done = pyqtSignal(object)

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg

    def run(self):
        self.done.emit(test_server(self.cfg))


class TestAllThread(QThread):
    result = pyqtSignal(int, object)
    progress = pyqtSignal(int, int, str)
    done_all = pyqtSignal()

    def __init__(self, servers: list, workers: int = WORKERS):
        super().__init__()
        self.servers = servers
        self.workers = workers
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        with _port_lock:
            _used_ports.clear()

        total = len(self.servers)
        if total == 0:
            self.done_all.emit()
            return

        try:
            done = 0
            self.progress.emit(0, total, f"تست سرورها… 0/{total}")
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                futs = {pool.submit(test_server, cfg): i for i, cfg in enumerate(self.servers)}
                for fut in as_completed(futs):
                    if self._cancelled:
                        break
                    idx = futs[fut]
                    try:
                        res = fut.result()
                    except Exception as e:
                        res = {"kind": "fail", "ms": None, "reason": f"error: {str(e)[:50]}",
                               "details": _make_failed_details("error")}
                    self.result.emit(idx, res)
                    done += 1
                    self.progress.emit(done, total, f"تست سرورها… {done}/{total}")
        finally:
            self.done_all.emit()