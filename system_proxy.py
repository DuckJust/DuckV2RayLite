# system_proxy.py
import ctypes
import json
import sys
from pathlib import Path

REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
BACKUP_FILE = Path(__file__).parent / "proxy_backup.json"

VALUE_NAMES = ("ProxyEnable", "ProxyServer", "ProxyOverride")


def _is_windows() -> bool:
    return sys.platform == "win32"


def _refresh_internet_settings() -> None:
    try:
        wininet = ctypes.windll.Wininet
        wininet.InternetSetOptionW(0, 39, 0, 0)  # SETTINGS_CHANGED
        wininet.InternetSetOptionW(0, 37, 0, 0)  # REFRESH
    except Exception:
        pass


def _read_proxy_state() -> dict:
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
    state = {}
    try:
        for name in VALUE_NAMES:
            try:
                val, _ = winreg.QueryValueEx(key, name)
                state[name] = val
            except FileNotFoundError:
                state[name] = None
    finally:
        winreg.CloseKey(key)
    return state


def _write_proxy_state(state: dict) -> None:
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_WRITE)
    try:
        for name in VALUE_NAMES:
            val = state.get(name)
            if val is None:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
            elif isinstance(val, int):
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, val)
            else:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(val))
    finally:
        winreg.CloseKey(key)
    _refresh_internet_settings()


def has_backup() -> bool:
    return _is_windows() and BACKUP_FILE.exists()


def backup_current() -> None:
    """قبل از تغییر، وضعیت فعلی را در فایل ذخیره می‌کند."""
    if not _is_windows():
        return
    if BACKUP_FILE.exists():
        return  # قبلاً بکاپ گرفته شده، دست نزن
    state = _read_proxy_state()
    BACKUP_FILE.write_text(json.dumps(state), encoding="utf-8")


def set_system_proxy(enable: bool, host: str = "127.0.0.1", port: int = 10809) -> None:
    if not _is_windows():
        return
    state = _read_proxy_state()
    if enable:
        state["ProxyEnable"] = 1
        state["ProxyServer"] = f"{host}:{port}"
        state["ProxyOverride"] = "<local>;127.0.0.1;localhost"
    else:
        state["ProxyEnable"] = 0
    _write_proxy_state(state)


def restore_backup() -> None:
    """تنظیمات اصلی را برمی‌گرداند. اگر بکاپ نبود، فقط پروکسی را خاموش می‌کند."""
    if not _is_windows():
        return
    if BACKUP_FILE.exists():
        try:
            state = json.loads(BACKUP_FILE.read_text(encoding="utf-8"))
            _write_proxy_state(state)
        finally:
            try:
                BACKUP_FILE.unlink(missing_ok=True)
            except Exception:
                pass
        return

    # بکاپ نبود: حداقل کاری که می‌توانیم بکنیم، خاموش کردن پروکسی سیستم است
    try:
        state = _read_proxy_state()
        if state.get("ProxyEnable"):
            state["ProxyEnable"] = 0
            _write_proxy_state(state)
    except Exception:
        pass