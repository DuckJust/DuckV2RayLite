# traffic_monitor.py
import json
import subprocess
import sys
import time

from PyQt5.QtCore import QThread, pyqtSignal

from xray_core import API_PORT, XRAY_EXE


def _creation_flags():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def query_stats(api_port: int = API_PORT):
    """Returns (uplink_bytes, downlink_bytes) از API داخلی Xray."""
    try:
        result = subprocess.run(
            [
                str(XRAY_EXE), "api", "statsquery",
                f"--server=127.0.0.1:{api_port}",
                "-pattern", "inbound",
            ],
            capture_output=True, text=True, timeout=3,
            creationflags=_creation_flags(),
        )
        if result.returncode != 0:
            return 0, 0
        data = json.loads(result.stdout or "{}")
        up = down = 0
        for stat in data.get("stat", []) or []:
            name = stat.get("name", "")
            if ">>>api>>>" in name:  # ترافیک خود API را حساب نکن
                continue
            try:
                value = int(stat.get("value", 0) or 0)
            except (TypeError, ValueError):
                continue
            if ">>>uplink" in name:
                up += value
            elif ">>>downlink" in name:
                down += value
        return up, down
    except Exception:
        return 0, 0


class TrafficMonitor(QThread):
    # up_bps, down_bps, total_up_bytes, total_down_bytes
    updated = pyqtSignal(int, int, int, int)

    def __init__(self, api_port: int = API_PORT, interval: float = 1.0):
        super().__init__()
        self.api_port = api_port
        self.interval = interval
        self._running = True
        self._last_up = 0
        self._last_down = 0
        self._last_time = None

    def stop(self):
        self._running = False

    def run(self):
        # اولین نمونه برای baseline
        time.sleep(0.4)
        while self._running:
            try:
                up, down = query_stats(self.api_port)
            except Exception:
                up, down = self._last_up, self._last_down

            now = time.time()
            if self._last_time is None:
                self._last_up = up
                self._last_down = down
                self._last_time = now
            else:
                dt = now - self._last_time
                if dt > 0:
                    up_speed = max(0, int((up - self._last_up) / dt))
                    down_speed = max(0, int((down - self._last_down) / dt))
                    self.updated.emit(up_speed, down_speed, up, down)
                self._last_up = up
                self._last_down = down
                self._last_time = now

            # انتظار کوتاه‌تر برای واکنش سریع به stop()
            slept = 0.0
            while self._running and slept < self.interval:
                time.sleep(0.1)
                slept += 0.1