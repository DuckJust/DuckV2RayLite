# main.py
from __future__ import annotations

import json
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from PyQt5.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QBoxLayout, QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QProgressBar, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QTextEdit,
)

import flags
from sub_parser import parse_subscription
from xray_core import (
    API_PORT, HTTP_PORT, XRAY_EXE, build_full_config,
    read_log_tail, start_xray, kill_zombie_xray,
)
from system_proxy import (
    backup_current, has_backup, restore_backup, set_system_proxy,
)
from ping_test import TestAllThread, TestOneThread
from traffic_monitor import TrafficMonitor

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
SUB_FILE = Path(__file__).parent / "subscriptions.json"
CONSUMPTION_FILE = Path(__file__).parent / "consumption.json"


# ---------------------- Global Exception Handler ----------------------

def global_excepthook(exc_type, exc_value, exc_tb):
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    print("\n" + "=" * 50)
    print("UNHANDLED EXCEPTION:")
    print(tb)
    print("=" * 50 + "\n")

    try:
        dlg = QDialog()
        dlg.setWindowTitle("خطای پیش‌بینی نشده")
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        dlg.resize(600, 400)
        dlg.setLayoutDirection(Qt.RightToLeft)

        layout = QVBoxLayout(dlg)
        lbl = QLabel(
            "یک خطای پیش‌بینی نشده در برنامه رخ داده است.\nمتن خطا در پایین نمایش داده شده و در کنسول نیز ثبت شده است:")
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(lbl)

        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(tb)
        txt.setLayoutDirection(Qt.LeftToRight)
        layout.addWidget(txt)

        btn = QPushButton("بستن")
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn)

        dlg.exec_()
    except Exception:
        pass


sys.excepthook = global_excepthook


# ---------------------- Formatting ----------------------

def format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.2f} GB"


def format_rate(n: int) -> str:
    return format_bytes(n) + "/s"


def format_total(n: int) -> str:
    if n <= 0:
        return "—"
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.2f} MB"
    return f"{n / 1024 ** 3:.2f} GB"


# ---------------------- Storage ----------------------

def load_store() -> dict:
    if SUB_FILE.exists():
        try:
            data = json.loads(SUB_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError
            data.setdefault("subscriptions", [])
            data.setdefault("last_id", None)
            for sub in data["subscriptions"]:
                sub.setdefault("id", uuid.uuid4().hex[:12])
                sub.setdefault("name", "ساب")
                sub.setdefault("url", "")
                sub.setdefault("servers", [])
            return data
        except Exception as e:
            print(f"[store] load failed: {e}")
    return {"subscriptions": [], "last_id": None}


def save_store(store: dict) -> None:
    try:
        SUB_FILE.write_text(
            json.dumps(store, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[store] save failed: {e}")


def guess_name(url: str) -> str:
    try:
        host = urlparse(url).hostname
        if host:
            return host
    except Exception:
        pass
    return "ساب جدید"


class ConsumptionStore:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self.data = raw
            except Exception as e:
                print(f"[consumption] load failed: {e}")

    def _save(self):
        try:
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"[consumption] save failed: {e}")

    def get(self, key: str) -> dict:
        return self.data.get(key, {
            "total_up": 0, "total_down": 0,
            "first_seen": None, "last_seen": None,
            "sessions": [],
        })

    def total_bytes(self, key: str) -> int:
        s = self.get(key)
        return int(s.get("total_up", 0)) + int(s.get("total_down", 0))

    def add_session(self, key: str, up: int, down: int,
                    start_ts: float, end_ts: float, duration: int):
        if up <= 0 and down <= 0:
            return
        entry = self.get(key)
        entry["total_up"] = int(entry.get("total_up", 0)) + up
        entry["total_down"] = int(entry.get("total_down", 0)) + down
        entry["first_seen"] = entry.get("first_seen") or \
                              datetime.fromtimestamp(start_ts).isoformat(timespec="seconds")
        entry["last_seen"] = \
            datetime.fromtimestamp(end_ts).isoformat(timespec="seconds")
        sessions = entry.setdefault("sessions", [])
        sessions.append({
            "up": up, "down": down,
            "start": datetime.fromtimestamp(start_ts).isoformat(timespec="seconds"),
            "end": datetime.fromtimestamp(end_ts).isoformat(timespec="seconds"),
            "duration": int(duration),
        })
        if len(sessions) > 100:
            entry["sessions"] = sessions[-100:]
        self.data[key] = entry
        self._save()


# ---------------------- Helpers ----------------------

class NumericTreeItem(QTreeWidgetItem):
    def __init__(self, parent, strings, value=None):
        super().__init__(parent, strings)
        self._value = value

    def __lt__(self, other):
        if isinstance(other, NumericTreeItem):
            tree = self.treeWidget()
            if tree and tree.sortColumn() == 0:
                a, b = self._value, other._value
                if a is None and b is None:
                    return False
                if a is None:
                    return False
                if b is None:
                    return True
                return a < b
        return super().__lt__(other)


class SpeedChart(QWidget):
    def __init__(self, max_points: int = 60):
        super().__init__()
        self.max_points = max_points
        self.down_samples = [0] * max_points
        self.up_samples = [0] * max_points
        self.setMinimumHeight(70)
        self.setMaximumHeight(110)

    def add_sample(self, up_speed: int, down_speed: int):
        self.down_samples.append(down_speed)
        self.up_samples.append(up_speed)
        if len(self.down_samples) > self.max_points:
            self.down_samples.pop(0)
            self.up_samples.pop(0)
        self.update()

    def reset(self):
        self.down_samples = [0] * self.max_points
        self.up_samples = [0] * self.max_points
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor("#20242e"))
        n = len(self.down_samples)
        if n < 2 or w < 4:
            painter.end()
            return
        max_val = max(max(self.down_samples), max(self.up_samples), 1024)
        dx = w / (n - 1)
        inner_h = h - 6

        def draw_series(samples, fill_color, line_color):
            path = QPainterPath()
            path.moveTo(0, h)
            for i, v in enumerate(samples):
                x = i * dx
                y = h - (v / max_val) * inner_h
                path.lineTo(x, y)
            path.lineTo(w, h)
            path.closeSubpath()
            painter.fillPath(path, fill_color)

            line = QPainterPath()
            line.moveTo(0, h - (samples[0] / max_val) * inner_h)
            for i, v in enumerate(samples[1:], 1):
                x = i * dx
                y = h - (v / max_val) * inner_h
                line.lineTo(x, y)
            painter.setPen(QPen(line_color, 1.4))
            painter.drawPath(line)

        draw_series(self.down_samples, QColor(76, 175, 80, 90), QColor("#66bb6a"))
        draw_series(self.up_samples, QColor(33, 150, 243, 90), QColor("#42a5f5"))

        painter.setPen(QColor("#808080"))
        painter.drawText(6, 14, f"max {format_rate(int(max_val))}")
        painter.end()


def verify_xray():
    if not XRAY_EXE.exists():
        return False, "xray.exe پیدا نشد. از GitHub دانلود کن و کنار main.py بگذار."
    try:
        size = XRAY_EXE.stat().st_size
        with open(XRAY_EXE, "rb") as f:
            header = f.read(2)
    except Exception as e:
        return False, f"خطا در خواندن فایل: {e}"
    if header != b"MZ":
        return False, f"xray.exe یک exe سالم نیست."
    if size < 5 * 1024 * 1024:
        return False, f"xray.exe حجمش فقط {size // 1024} KB است — خیلی کوچک است."
    return True, f"xray.exe سالم است ({size // 1024 // 1024} MB)"


# ---------------------- Flag prefetcher ----------------------

class FlagPrefetcher(QThread):
    finished_flags = pyqtSignal()

    def __init__(self, codes: list[str]):
        super().__init__()
        self.codes = list(codes)

    def run(self):
        for code in self.codes:
            if code:
                flags.ensure_flag(code)
        self.finished_flags.emit()


# ---------------------- Fetch worker ----------------------

class FetchWorker(QObject):
    done = pyqtSignal(list)
    error = pyqtSignal(str)


def start_fetch(url: str, worker: FetchWorker) -> threading.Thread:
    def _run():
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
            r.raise_for_status()
            worker.done.emit(parse_subscription(r.text))
        except Exception as e:
            worker.error.emit(str(e))

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


# ---------------------- Dialogs ----------------------

class AddSubDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("افزودن ساب‌سکریپشن")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(460)
        self.setLayoutDirection(Qt.RightToLeft)

        form = QFormLayout(self)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("اختیاری — اگر خالی باشد از دامنه استفاده می‌شود")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://example.com/sub/...")
        form.addRow("نام:", self.name_input)
        form.addRow("لینک:", self.url_input)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("افزودن")
        btns.button(QDialogButtonBox.Cancel).setText("انصراف")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def values(self):
        return self.name_input.text().strip(), self.url_input.text().strip()


class FetchDialog(QDialog):
    def __init__(self, title: str, url: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(380)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setLayoutDirection(Qt.RightToLeft)

        self.servers: list | None = None
        self.error_msg: str | None = None
        self._cancelled = False

        self.message = QLabel("در حال دریافت ساب‌سکریپشن...")
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(10)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #c62828; padding: 4px;")
        self.error_label.setWordWrap(True)
        self.error_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.error_label.hide()
        self.cancel_btn = QPushButton("انصراف")
        self.cancel_btn.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.message)
        layout.addWidget(self.progress)
        layout.addWidget(self.error_label)
        layout.addWidget(self.cancel_btn)

        self._worker = FetchWorker()
        self._worker.done.connect(self._on_success)
        self._worker.error.connect(self._on_error)
        self._thread = start_fetch(url, self._worker)

    def _on_success(self, servers):
        if self._cancelled:
            return
        self.servers = servers
        self.accept()

    def _on_error(self, msg):
        if self._cancelled:
            return
        self.error_msg = msg
        self.message.setText("خطا در بارگذاری سرور:")
        self.error_label.setText(msg)
        self.error_label.show()
        self.progress.hide()
        self.cancel_btn.setText("بستن")

    def reject(self):
        self._cancelled = True
        try:
            self._worker.done.disconnect(self._on_success)
            self._worker.error.disconnect(self._on_error)
        except Exception:
            pass
        super().reject()


class HistoryDialog(QDialog):
    def __init__(self, cfg: dict, entry: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"تاریخچه مصرف — {cfg.get('name', '')}")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(560, 460)
        layout = QVBoxLayout(self)

        total_up = int(entry.get("total_up", 0))
        total_down = int(entry.get("total_down", 0))
        total = total_up + total_down
        first = entry.get("first_seen") or "—"
        last = entry.get("last_seen") or "—"
        session_count = len(entry.get("sessions", []))

        summary = QLabel(
            f"<div dir='rtl' style='font-size:14px; line-height:1.7'>"
            f"<b>کل مصرف:</b> {format_total(total)}<br>"
            f"<b>دانلود:</b> {format_total(total_down)} &nbsp;&nbsp;&nbsp; "
            f"<b>آپلود:</b> {format_total(total_up)}<br>"
            f"<b>اولین استفاده:</b> {first}<br>"
            f"<b>آخرین استفاده:</b> {last}<br>"
            f"<b>تعداد نشست‌ها:</b> {session_count}"
            f"</div>"
        )
        summary.setStyleSheet("padding: 10px; background: #f5f5f5; border-radius: 4px;")
        layout.addWidget(summary)

        layout.addWidget(QLabel("<b>نشست‌های اخیر:</b>"))

        table = QTreeWidget()
        table.setHeaderLabels(["شروع", "مدت", "دانلود", "آپلود"])
        h = table.header()
        h.setDefaultAlignment(Qt.AlignCenter)
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table.setEditTriggers(QTreeWidget.NoEditTriggers)
        table.setRootIsDecorated(False)
        table.setAlternatingRowColors(True)

        for s in reversed(entry.get("sessions", [])):
            item = QTreeWidgetItem(table)
            item.setText(0, s.get("start", "—"))
            item.setText(1, self._fmt_duration(int(s.get("duration", 0))))
            item.setText(2, format_total(int(s.get("down", 0))))
            item.setText(3, format_total(int(s.get("up", 0))))
            item.setTextAlignment(0, Qt.AlignCenter)

        layout.addWidget(table, 1)
        close_btn = QPushButton("بستن")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    @staticmethod
    def _fmt_duration(seconds: int) -> str:
        if seconds < 60:
            return f"{seconds} ثانیه"
        if seconds < 3600:
            return f"{seconds // 60} دقیقه"
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h} ساعت {m} دقیقه"


class GlobalHistoryDialog(QDialog):
    def __init__(self, consumption_store: ConsumptionStore, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تاریخچه مصرف کل (همه سرورها)")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(640, 500)
        layout = QVBoxLayout(self)

        total_up = 0
        total_down = 0
        for key, data in consumption_store.data.items():
            total_up += int(data.get("total_up", 0))
            total_down += int(data.get("total_down", 0))

        total = total_up + total_down

        summary = QLabel(
            f"<div dir='rtl' style='font-size:14px; line-height:1.7'>"
            f"<b>کل مصرف همه سرورها:</b> {format_total(total)}<br>"
            f"<b>کل دانلود:</b> {format_total(total_down)} &nbsp;&nbsp;&nbsp; "
            f"<b>کل آپلود:</b> {format_total(total_up)}<br>"
            f"<b>تعداد سرورهای دارای سابقه:</b> {len(consumption_store.data)}"
            f"</div>"
        )
        summary.setStyleSheet("padding: 10px; background: #e3f2fd; border-radius: 4px;")
        layout.addWidget(summary)

        layout.addWidget(QLabel("<b>تفکیک بر اساس سرور (بیشترین مصرف در بالا):</b>"))
        table = QTreeWidget()
        table.setHeaderLabels(["نام سرور", "دانلود", "آپلود", "کل مصرف"])
        h = table.header()
        h.setDefaultAlignment(Qt.AlignCenter)
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table.setEditTriggers(QTreeWidget.NoEditTriggers)
        table.setRootIsDecorated(False)
        table.setAlternatingRowColors(True)

        sorted_servers = []
        for key, data in consumption_store.data.items():
            up = int(data.get("total_up", 0))
            down = int(data.get("total_down", 0))
            sorted_servers.append((key, up, down, up + down))

        sorted_servers.sort(key=lambda x: x[3], reverse=True)

        for key, up, down, tot in sorted_servers:
            # باگ فیکس شد: استفاده از maxsplit=3 برای اینکه اگر اسم سرور شامل | بود، اسم کامل حفظ شود
            parts = key.split("|", 3)
            name = parts[3] if len(parts) >= 4 else key
            
            item = QTreeWidgetItem(table)
            item.setText(0, name)
            item.setText(1, format_total(down))
            item.setText(2, format_total(up))
            item.setText(3, format_total(tot))
            item.setTextAlignment(0, Qt.AlignCenter)

        layout.addWidget(table, 1)
        close_btn = QPushButton("بستن")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


# ---------------------- Core thread ----------------------

class CoreThread(QThread):
    started_ok = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.proc = None

    def run(self):
        kill_zombie_xray()

        try:
            self.proc = start_xray(self.config)
        except Exception as e:
            self.error.emit(str(e))
            return
        time.sleep(1.0)
        if self.proc.poll() is not None:
            self.error.emit("xray اجرا شد ولی فوراً بسته شد:\n" + read_log_tail())
            return
        self.started_ok.emit()
        self.proc.wait()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(3)
            except Exception:
                self.proc.kill()


# ---------------------- Main window ----------------------

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("V2Ray Lite")

        w, h = 800, 600
        self.setFixedSize(w, h)

        screen = QApplication.primaryScreen().availableGeometry()
        frame_geom = self.frameGeometry()
        frame_geom.moveCenter(screen.center())
        self.move(frame_geom.topLeft())

        self.store = load_store()
        self.consumption = ConsumptionStore(CONSUMPTION_FILE)
        self.current_sub_id = None
        self.servers: list = []

        self.connected_key: str | None = None
        self._current_session_key: str | None = None
        self._session_start_ts: float | None = None
        self._session_up = 0
        self._session_down = 0

        self.core_thread: CoreThread | None = None
        self.test_thread: TestAllThread | None = None
        self.one_thread: TestOneThread | None = None
        self.traffic_monitor: TrafficMonitor | None = None
        self.flag_prefetcher: FlagPrefetcher | None = None
        self._keep_alive = None

        try:
            if has_backup():
                restore_backup()
        except Exception as e:
            print(f"[startup] restore failed: {e}")

        self._build_ui()

        ok, msg = verify_xray()
        if not ok:
            self._set_status(f"⚠️ {msg}", is_error=True)

        self._populate_sub_list()
        if self.sub_list.count() == 0:
            self._set_status("هنوز سابی اضافه نکردی — روی «+ افزودن ساب» بزن")

    def _set_status(self, text: str, is_error=False):
        color = "#c62828" if is_error else "#000000"
        html = f'<div dir="rtl" style="text-align: right; color: {color}; font-family: Tahoma, Arial; font-size: 11pt;">{text}</div>'
        self.status.setText(html)

    def _show_error_dialog(self, title, message):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        dlg.resize(600, 400)
        dlg.setLayoutDirection(Qt.RightToLeft)

        layout = QVBoxLayout(dlg)
        lbl = QLabel(
            "متن خطا در پایین نمایش داده شده است. می‌توانید آن را کپی کنید:\n(لاگ کامل در کنسول پایتون نیز ثبت شده است)")
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(lbl)

        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(message)
        txt.setLayoutDirection(Qt.LeftToRight)
        layout.addWidget(txt)

        btn = QPushButton("بستن")
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn)

        dlg.exec_()

    # ---------- UI ----------
    def _build_ui(self):
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["پینگ", "نوع", "نام / سرویس", "آدرس", "پورت", "کل مصرف"])
        h = self.tree.header()
        h.setDefaultAlignment(Qt.AlignCenter)
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        h.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.tree.setSelectionBehavior(QTreeWidget.SelectRows)
        self.tree.setSelectionMode(QTreeWidget.SingleSelection)
        self.tree.setEditTriggers(QTreeWidget.NoEditTriggers)
        self.tree.setSortingEnabled(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.doubleClicked.connect(self.on_row_double_click)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.on_tree_context_menu)

        self.test_all_btn = QPushButton("تست همه")
        self.test_one_btn = QPushButton("تست انتخاب‌شده")
        self.history_btn = QPushButton("تاریخچه این سرور")
        self.global_history_btn = QPushButton("تاریخچه مصرف کل")
        self.global_history_btn.setStyleSheet("background-color: #e3f2fd;")

        self.show_all_sites_cb = QCheckBox("نمایش همه سایت‌های تست‌شده (حتی ناموفق‌ها)")
        self.show_all_sites_cb.setChecked(False)
        self.show_all_sites_cb.stateChanged.connect(self._populate_tree)

        self.expand_all_btn = QPushButton("باز کردن همه")
        self.expand_all_btn.clicked.connect(self.tree.expandAll)
        self.collapse_all_btn = QPushButton("بستن همه")
        self.collapse_all_btn.clicked.connect(self.tree.collapseAll)

        self.connect_btn = QPushButton("اتصال")
        self.disconnect_btn = QPushButton("قطع")
        self.disconnect_btn.setEnabled(False)

        self.speed_chart = SpeedChart(max_points=60)
        self.speed_label = QLabel("↓ 0 B/s    ↑ 0 B/s")
        self.speed_label.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 13px; font-weight: bold; padding: 2px 6px;")
        self.total_label = QLabel("مصرف کل این نشست:  0 B")
        self.total_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #2e7d32; padding: 4px 6px;")
        self.breakdown_label = QLabel("↓ 0 B    ↑ 0 B")
        self.breakdown_label.setStyleSheet("font-family: Consolas, monospace; color: #666; padding: 0 6px 4px 6px;")

        self.status = QLabel("")
        self.status.setFixedHeight(40)
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.RichText)
        self.status.setStyleSheet("padding:6px; background:#f3f3f3; border-radius:4px;")
        self.status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._set_status("آماده")

        test_row1 = QHBoxLayout()
        test_row1.addWidget(self.test_all_btn)
        test_row1.addWidget(self.test_one_btn)
        test_row1.addWidget(self.history_btn)
        test_row1.addWidget(self.global_history_btn)

        test_row2 = QHBoxLayout()
        test_row2.addWidget(self.show_all_sites_cb)
        test_row2.addWidget(self.expand_all_btn)
        test_row2.addWidget(self.collapse_all_btn)

        conn_row = QHBoxLayout()
        conn_row.addWidget(self.connect_btn)
        conn_row.addWidget(self.disconnect_btn)

        main_col = QVBoxLayout()
        main_col.addWidget(self.tree, 1)
        main_col.addLayout(test_row1)
        main_col.addLayout(test_row2)
        main_col.addLayout(conn_row)
        main_col.addWidget(self.speed_chart)
        main_col.addWidget(self.speed_label)
        main_col.addWidget(self.total_label)
        main_col.addWidget(self.breakdown_label)
        main_col.addWidget(self.status)

        sidebar_label = QLabel("ساب‌سکریپشن‌ها")
        sidebar_label.setStyleSheet("font-weight: bold; padding: 4px;")
        self.sub_list = QListWidget()
        self.sub_list.setMinimumWidth(230)
        self.sub_list.setMaximumWidth(300)
        self.sub_list.setStyleSheet(
            "QListWidget::item { padding: 8px; } QListWidget::item:selected { background: #1976d2; color: white; }")

        self.add_sub_btn = QPushButton("+ افزودن ساب")
        self.refresh_sub_btn = QPushButton("↻ به‌روزرسانی ساب")
        self.delete_sub_btn = QPushButton("🗑 حذف ساب")
        self.refresh_sub_btn.setEnabled(False)
        self.delete_sub_btn.setEnabled(False)

        row2 = QHBoxLayout()
        row2.addWidget(self.refresh_sub_btn)
        row2.addWidget(self.delete_sub_btn)

        sidebar = QVBoxLayout()
        sidebar.addWidget(sidebar_label)
        sidebar.addWidget(self.sub_list, 1)
        sidebar.addWidget(self.add_sub_btn)
        sidebar.addLayout(row2)

        outer = QBoxLayout(QBoxLayout.LeftToRight, self)
        outer.addLayout(main_col, 1)
        outer.addLayout(sidebar, 0)

        self.sub_list.currentItemChanged.connect(self.on_sub_item_changed)
        self.add_sub_btn.clicked.connect(self.on_add_sub)
        self.refresh_sub_btn.clicked.connect(self.on_refresh_sub)
        self.delete_sub_btn.clicked.connect(self.on_delete_sub)
        self.test_all_btn.clicked.connect(self.on_test_all)
        self.test_one_btn.clicked.connect(self.on_test_selected)
        self.history_btn.clicked.connect(self.on_show_history)
        self.global_history_btn.clicked.connect(self.on_show_global_history)
        self.connect_btn.clicked.connect(self.on_connect)
        self.disconnect_btn.clicked.connect(self.on_disconnect)

    def _get_flag_icon(self, cfg: dict) -> QIcon | None:
        code = cfg.get("_country")
        if code is None:
            code = flags.detect_country_code(cfg.get("name", ""))
            cfg["_country"] = code
        if not code:
            return None
        path = flags.flag_path(code)
        if not (path.exists() and path.stat().st_size > 200):
            return None
        pix = QPixmap(str(path))
        if pix.isNull():
            return None
        pix = pix.scaledToHeight(20, Qt.SmoothTransformation)
        return QIcon(pix)

    def _prefetch_missing_flags(self):
        codes = set()
        for cfg in self.servers:
            code = cfg.get("_country")
            if code and not flags.flag_path(code).exists():
                codes.add(code)
        if not codes:
            return
        if self.flag_prefetcher is not None and self.flag_prefetcher.isRunning():
            return
        self.flag_prefetcher = FlagPrefetcher(sorted(codes))
        self.flag_prefetcher.finished_flags.connect(self._refresh_flag_icons)
        self.flag_prefetcher.start()

    def _refresh_flag_icons(self):
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            idx = item.data(0, Qt.UserRole)
            if idx is None or idx >= len(self.servers):
                continue
            cfg = self.servers[idx]
            icon = self._get_flag_icon(cfg)
            if icon is not None:
                item.setIcon(2, icon)

    def _populate_sub_list(self):
        self.sub_list.blockSignals(True)
        self.sub_list.clear()
        for sub in self.store["subscriptions"]:
            count = len(sub.get("servers", []))
            item = QListWidgetItem(f"{sub['name']}   ·  {count} سرور")
            item.setData(Qt.UserRole, sub["id"])
            item.setToolTip(sub.get("url", ""))
            self.sub_list.addItem(item)
        self.sub_list.blockSignals(False)

        target_id = self.current_sub_id or self.store.get("last_id")
        selected_row = -1
        for i in range(self.sub_list.count()):
            if self.sub_list.item(i).data(Qt.UserRole) == target_id:
                selected_row = i
                break
        if selected_row < 0 and self.sub_list.count() > 0:
            selected_row = 0

        if selected_row >= 0:
            self.sub_list.setCurrentRow(selected_row)
            self.on_sub_item_changed(self.sub_list.item(selected_row), None)
        else:
            self.servers = []
            self._populate_tree()

    def _current_sub(self) -> dict | None:
        if self.current_sub_id is None:
            return None
        for s in self.store["subscriptions"]:
            if s["id"] == self.current_sub_id:
                return s
        return None

    def _select_sub(self, sub_id: str):
        sub = next(
            (s for s in self.store["subscriptions"] if s["id"] == sub_id),
            None,
        )
        if sub is None:
            self.current_sub_id = None
            self.servers = []
            self._populate_tree()
            return
        self.current_sub_id = sub_id
        self.store["last_id"] = sub_id
        save_store(self.store)
        self.servers = sub.setdefault("servers", [])
        self._populate_tree()
        self._set_status(f"«{sub['name']}» — {len(self.servers)} سرور")
        self.refresh_sub_btn.setEnabled(True)
        self.delete_sub_btn.setEnabled(True)

    def on_sub_item_changed(self, current, previous):
        if current is None:
            return
        sub_id = current.data(Qt.UserRole)
        if sub_id == self.current_sub_id:
            return
        self._select_sub(sub_id)

    def on_add_sub(self):
        dlg = AddSubDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        name, url = dlg.values()
        if not url:
            self._set_status("لینک ساب را وارد کنید", is_error=True)
            return
        if not name:
            name = guess_name(url)

        fetch_dlg = FetchDialog("دریافت ساب‌سکریپشن", url, self)
        result = fetch_dlg.exec_()
        self._keep_alive = fetch_dlg

        if result != QDialog.Accepted or fetch_dlg.servers is None:
            if fetch_dlg.error_msg:
                self._set_status(f"خطای دریافت ساب: {fetch_dlg.error_msg}", is_error=True)
            else:
                self._set_status("دریافت ساب لغو شد", is_error=True)
            return

        servers = fetch_dlg.servers
        sub = {
            "id": uuid.uuid4().hex[:12],
            "name": name,
            "url": url,
            "servers": servers,
        }
        self.store["subscriptions"].append(sub)
        self.store["last_id"] = sub["id"]
        save_store(self.store)
        self.current_sub_id = None
        self._populate_sub_list()
        self._set_status(f"«{name}» با {len(servers)} سرور اضافه شد")

    def on_refresh_sub(self):
        sub = self._current_sub()
        if sub is None or not sub.get("url"):
            self._set_status("این ساب لینک ندارد", is_error=True)
            return

        fetch_dlg = FetchDialog(f"به‌روزرسانی «{sub['name']}»", sub["url"], self)
        result = fetch_dlg.exec_()
        self._keep_alive = fetch_dlg

        if result != QDialog.Accepted or fetch_dlg.servers is None:
            if fetch_dlg.error_msg:
                self._set_status(f"خطای به‌روزرسانی: {fetch_dlg.error_msg}", is_error=True)
            else:
                self._set_status("به‌روزرسانی لغو شد", is_error=True)
            return

        new_servers = fetch_dlg.servers
        old_by_key = {self._server_key(s): s for s in sub.get("servers", [])}
        merged = []
        preserved = 0
        for new_srv in new_servers:
            key = self._server_key(new_srv)
            if key in old_by_key:
                old = old_by_key[key]
                for field in ("_latency", "_kind", "_reason", "_country", "_details"):
                    if field in old:
                        new_srv[field] = old[field]
                preserved += 1
            merged.append(new_srv)

        sub["servers"] = merged
        self.store["last_id"] = sub["id"]
        save_store(self.store)
        self.current_sub_id = None
        self._populate_sub_list()
        self._set_status(
            f"«{sub['name']}» به‌روزرسانی شد — {len(merged)} سرور "
            f"({preserved} نتیجه تست حفظ شد)"
        )

    def on_delete_sub(self):
        sub = self._current_sub()
        if sub is None:
            return
        msg = QMessageBox(self)
        msg.setWindowFlags(msg.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        msg.setWindowTitle("حذف ساب")
        msg.setText(
            f"ساب «{sub['name']}» با {len(sub.get('servers', []))} سرور حذف شود؟\n(تاریخچه مصرف سرورها حفظ می‌شود)")
        msg.setIcon(QMessageBox.Question)
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)
        if msg.exec_() != QMessageBox.Yes:
            return

        self.store["subscriptions"] = [
            s for s in self.store["subscriptions"] if s["id"] != sub["id"]
        ]
        if self.store.get("last_id") == sub["id"]:
            self.store["last_id"] = None
        save_store(self.store)
        self.current_sub_id = None
        self.servers = []
        self.refresh_sub_btn.setEnabled(False)
        self.delete_sub_btn.setEnabled(False)
        self._populate_sub_list()
        if self.sub_list.count() == 0:
            self._populate_tree()
            self._set_status("همه ساب‌ها حذف شدند")

    # ---------- Tree ----------
    def _server_key(self, cfg: dict) -> str:
        return f"{cfg['type']}|{cfg['address']}|{cfg['port']}|{cfg['name']}"

    def _ping_color(self, cfg: dict):
        kind = cfg.get("_kind", "__untested__")
        lat = cfg.get("_latency")
        if kind == "__untested__":
            return QColor("#616161")
        if kind == "fail" or lat is None:
            return QColor("#9e9e9e")
        if kind == "tcp":
            return QColor("#e65100")
        if lat < 200:
            return QColor("#2e7d32")
        if lat < 500:
            return QColor("#388e3c")
        if lat < 1000:
            return QColor("#f57c00")
        return QColor("#c62828")

    def _ping_text_and_value(self, cfg: dict):
        kind = cfg.get("_kind", "__untested__")
        lat = cfg.get("_latency")
        if kind == "__untested__":
            return "–", None
        if kind == "fail" or lat is None:
            return "×", None
        if kind == "http":
            return f"{lat} ms", lat
        if kind == "tcp":
            return f"{lat} ms (TCP)", 2_000_000 + lat
        return "–", None

    def _add_children_to_item(self, item: QTreeWidgetItem, cfg: dict):
        item.takeChildren()
        details = cfg.get("_details", [])
        has_child = False
        show_all = self.show_all_sites_cb.isChecked()

        for site in details:
            ms = site.get("ms")
            if ms is not None or show_all:
                has_child = True
                if ms is not None:
                    child = NumericTreeItem(item, [f"{ms} ms", "", f"✅ {site['name']}", "", "", ""], ms)
                    child.setForeground(0, QColor("#2e7d32"))
                    child.setForeground(2, QColor("#2e7d32"))
                else:
                    err = site.get("err", "failed")
                    child = NumericTreeItem(item, ["×", "", f"❌ {site['name']} ({err})", "", "", ""], None)
                    child.setForeground(0, QColor("#c62828"))
                    child.setForeground(2, QColor("#c62828"))

                child.setTextAlignment(0, Qt.AlignCenter)
                child.setTextAlignment(2, Qt.AlignCenter)

    def _update_tree_item(self, idx: int):
        was_sorting = self.tree.isSortingEnabled()
        self.tree.setSortingEnabled(False)
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.data(0, Qt.UserRole) == idx:
                cfg = self.servers[idx]
                text, val = self._ping_text_and_value(cfg)
                item.setText(0, text)
                if isinstance(item, NumericTreeItem):
                    item._value = val

                is_connected = (self.connected_key is not None and self._server_key(cfg) == self.connected_key)
                if is_connected:
                    for col in range(6):
                        item.setBackground(col, QColor("#c8e6c9"))
                        item.setForeground(col, QColor("#1b5e20"))
                else:
                    for col in range(6):
                        item.setBackground(col, QColor(0, 0, 0, 0))
                        item.setForeground(col, QColor("#000000"))
                    item.setForeground(0, self._ping_color(cfg))

                self._add_children_to_item(item, cfg)
                break
        self.tree.setSortingEnabled(was_sorting)

    def _update_connection_colors(self):
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            idx = item.data(0, Qt.UserRole)
            if idx is None or idx >= len(self.servers):
                continue
            cfg = self.servers[idx]
            is_connected = (self.connected_key is not None and self._server_key(cfg) == self.connected_key)
            if is_connected:
                for col in range(6):
                    item.setBackground(col, QColor("#c8e6c9"))
                    item.setForeground(col, QColor("#1b5e20"))
            else:
                for col in range(6):
                    item.setBackground(col, QColor(0, 0, 0, 0))
                    item.setForeground(col, QColor("#000000"))
                item.setForeground(0, self._ping_color(cfg))

    def _update_total_column(self):
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            idx = item.data(0, Qt.UserRole)
            if idx is None or idx >= len(self.servers):
                continue
            cfg = self.servers[idx]
            total = self.consumption.total_bytes(self._server_key(cfg))
            item.setText(5, format_total(total) if total > 0 else "—")

    def _populate_tree(self):
        selected_key = None
        cur = self._current_server()
        if cur is not None:
            selected_key = self._server_key(cur[0])

        self.tree.setSortingEnabled(False)
        self.tree.clear()
        for idx, cfg in enumerate(self.servers):
            text, val = self._ping_text_and_value(cfg)
            item = NumericTreeItem(self.tree,
                                   [text, cfg["type"].upper(), cfg["name"], cfg["address"], str(cfg["port"]), ""], val)
            item.setData(0, Qt.UserRole, idx)

            icon = self._get_flag_icon(cfg)
            if icon:
                item.setIcon(2, icon)

            total = self.consumption.total_bytes(self._server_key(cfg))
            item.setText(5, format_total(total) if total > 0 else "—")

            item.setTextAlignment(0, Qt.AlignCenter)
            item.setTextAlignment(1, Qt.AlignCenter)
            item.setTextAlignment(2, Qt.AlignCenter)
            item.setTextAlignment(3, Qt.AlignCenter)
            item.setTextAlignment(4, Qt.AlignCenter)
            item.setTextAlignment(5, Qt.AlignCenter)

            is_connected = (self.connected_key is not None and self._server_key(cfg) == self.connected_key)
            if is_connected:
                for col in range(6):
                    item.setBackground(col, QColor("#c8e6c9"))
                    item.setForeground(col, QColor("#1b5e20"))
            else:
                item.setForeground(0, self._ping_color(cfg))

            self._add_children_to_item(item, cfg)

            if selected_key is not None and self._server_key(cfg) == selected_key:
                self.tree.setCurrentItem(item)

        self.tree.setSortingEnabled(True)
        self._prefetch_missing_flags()

    def _current_server(self):
        item = self.tree.currentItem()
        if not item:
            return None
        if item.parent():
            item = item.parent()
        idx = item.data(0, Qt.UserRole)
        if idx is None or idx >= len(self.servers):
            return None
        return self.servers[idx], idx

    def on_row_double_click(self, index):
        item = self.tree.itemFromIndex(index)
        if not item:
            return
        self.tree.setCurrentItem(item)
        cur = self._current_server()
        if cur is None:
            return
        cfg, _ = cur
        dlg = HistoryDialog(cfg, self.consumption.get(self._server_key(cfg)), self)
        dlg.exec_()

    def on_tree_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
        self.tree.setCurrentItem(item)
        cur = self._current_server()
        if cur is None:
            return
        cfg, _ = cur
        menu = QMenu(self)
        test_action = menu.addAction("تست مجدد")
        history_action = menu.addAction("تاریخچه مصرف")
        menu.addSeparator()
        remove_action = menu.addAction("حذف از این ساب")
        action = menu.exec_(self.tree.viewport().mapToGlobal(pos))
        if action == test_action:
            self.on_test_selected()
        elif action == history_action:
            dlg = HistoryDialog(cfg, self.consumption.get(self._server_key(cfg)), self)
            dlg.exec_()
        elif action == remove_action:
            sub = self._current_sub()
            if sub:
                target = self._server_key(cfg)
                sub["servers"] = [
                    s for s in sub.get("servers", [])
                    if self._server_key(s) != target
                ]
                save_store(self.store)
                self.servers = sub["servers"]
                self._populate_tree()
                self._populate_sub_list()
                self._set_status(f"«{cfg['name']}» از ساب حذف شد")

    def on_show_history(self):
        cur = self._current_server()
        if cur is None:
            self._set_status("یک سرور انتخاب کنید", is_error=True)
            return
        cfg, _ = cur
        dlg = HistoryDialog(cfg, self.consumption.get(self._server_key(cfg)), self)
        dlg.exec_()

    def on_show_global_history(self):
        dlg = GlobalHistoryDialog(self.consumption, self)
        dlg.exec_()

    # ---------- Testing ----------
    def on_test_all(self):
        if not self.servers:
            self._set_status("این ساب سروری ندارد", is_error=True)
            return
        if self.test_thread is not None:
            self.test_thread.cancel()
            self._set_status("در حال لغو تست…")
            self.test_all_btn.setEnabled(False)
            return

        for cfg in self.servers:
            cfg.pop("_latency", None)
            cfg.pop("_kind", None)
            cfg.pop("_reason", None)
            cfg.pop("_details", None)
        self._populate_tree()

        self.test_thread = TestAllThread(list(self.servers))
        self.test_thread.result.connect(self.on_test_result)
        self.test_thread.progress.connect(self.on_test_progress)
        self.test_thread.done_all.connect(self.on_test_all_done)
        self.test_thread.start()

        self.test_all_btn.setText("لغو تست")
        self._set_status("شروع تست…")

    def on_test_result(self, idx: int, result: dict):
        if idx >= len(self.servers):
            return
        cfg = self.servers[idx]
        cfg["_latency"] = result.get("ms")
        cfg["_kind"] = result.get("kind")
        cfg["_reason"] = result.get("reason")
        cfg["_details"] = result.get("details", [])
        self._update_tree_item(idx)

    def on_test_progress(self, done: int, total: int, phase_label: str):
        self._set_status(phase_label)

    def on_test_all_done(self):
        self.test_thread = None
        self.test_all_btn.setEnabled(True)
        self.test_all_btn.setText("تست همه")
        self.tree.sortItems(0, Qt.AscendingOrder)
        save_store(self.store)
        http_ok = sum(1 for c in self.servers if c.get("_kind") == "http")
        tcp_ok = sum(1 for c in self.servers if c.get("_kind") == "tcp")
        failed = sum(1 for c in self.servers if c.get("_kind") == "fail")
        self._set_status(
            f"تست کامل شد — ✅ {http_ok} کارا | 🟡 {tcp_ok} فقط TCP | ❌ {failed} مرده"
        )

    def on_test_selected(self):
        cur = self._current_server()
        if cur is None:
            self._set_status("یک سرور انتخاب کنید", is_error=True)
            return
        cfg, idx = cur
        if self.one_thread is not None:
            return
        self.test_one_btn.setEnabled(False)
        self._set_status("در حال تست...")
        self.one_thread = TestOneThread(cfg)
        self.one_thread.done.connect(lambda res, i=idx: self._on_one_done(i, res))
        self.one_thread.start()

    def _on_one_done(self, idx, result: dict):
        cfg = self.servers[idx]
        cfg["_latency"] = result.get("ms")
        cfg["_kind"] = result.get("kind")
        cfg["_reason"] = result.get("reason")
        cfg["_details"] = result.get("details", [])
        self._update_tree_item(idx)
        save_store(self.store)
        self.test_one_btn.setEnabled(True)
        self.one_thread = None
        kind = result.get("kind")
        ms = result.get("ms")
        if kind == "http":
            self._set_status(f"✅ نتیجه: {ms} ms")
        elif kind == "tcp":
            self._set_status(
                f"🟡 TCP ok ({ms} ms) ولی تونل جواب نداد: {result.get('reason')}", is_error=True
            )
        else:
            self._set_status(f"❌ {result.get('reason')}", is_error=True)

    # ---------- Traffic / session ----------
    def _start_monitor(self):
        if self.traffic_monitor is not None:
            return
        self.speed_chart.reset()
        self.speed_label.setText("↓ 0 B/s    ↑ 0 B/s")
        self.total_label.setText("مصرف کل این نشست:  0 B")
        self.breakdown_label.setText("↓ 0 B    ↑ 0 B")
        self.traffic_monitor = TrafficMonitor(api_port=API_PORT, interval=1.0)
        self.traffic_monitor.updated.connect(self.on_traffic_update)
        self.traffic_monitor.start()

    def _stop_monitor(self):
        if self.traffic_monitor is not None:
            self.traffic_monitor.stop()
            self.traffic_monitor.wait(2000)
            self.traffic_monitor = None

    def on_traffic_update(self, up_speed, down_speed, total_up, total_down):
        self.speed_chart.add_sample(up_speed, down_speed)
        self.speed_label.setText(
            f"↓ {format_rate(down_speed)}    ↑ {format_rate(up_speed)}"
        )
        grand_total = total_up + total_down
        self.total_label.setText(f"مصرف کل این نشست:  {format_total(grand_total)}")
        self.breakdown_label.setText(
            f"↓ {format_total(total_down)}    ↑ {format_total(total_up)}"
        )
        self._session_up = total_up
        self._session_down = total_down

    def _begin_session(self, cfg: dict):
        self._current_session_key = self._server_key(cfg)
        self._session_start_ts = time.time()
        self._session_up = 0
        self._session_down = 0

    def _finalize_session(self):
        if self._current_session_key is None or self._session_start_ts is None:
            self._current_session_key = None
            self._session_start_ts = None
            return
        if self._session_up == 0 and self._session_down == 0:
            self._current_session_key = None
            self._session_start_ts = None
            return
        now = time.time()
        duration = int(now - self._session_start_ts)
        self.consumption.add_session(
            self._current_session_key,
            self._session_up, self._session_down,
            self._session_start_ts, now, duration,
        )
        self._current_session_key = None
        self._session_start_ts = None
        self._session_up = 0
        self._session_down = 0
        self._update_total_column()

    # ---------- Connect ----------
    def on_connect(self):
        cur = self._current_server()
        if cur is None:
            self._set_status("یک سرور انتخاب کنید", is_error=True)
            return
        cfg, _ = cur

        ok, msg = verify_xray()
        if not ok:
            self._set_status(f"⚠️ {msg}", is_error=True)
            return

        if self.core_thread is not None:
            self._finalize_session()
            self._stop_monitor()
            self.core_thread.stop()
            self.core_thread.wait(3000)
            self.core_thread = None
            self.connected_key = None
            self._update_connection_colors()

        try:
            full = build_full_config(cfg)
        except Exception as e:
            self._set_status(f"خطا در ساخت کانفیگ: {e}", is_error=True)
            return

        try:
            backup_current()
        except Exception as e:
            print(f"[connect] backup failed: {e}")

        self.core_thread = CoreThread(full)
        self.core_thread.started_ok.connect(lambda c=cfg: self.on_core_started(c))
        self.core_thread.error.connect(self.on_core_error)
        self.core_thread.start()

        self._set_status("در حال اتصال...")
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(True)

    def on_core_started(self, cfg: dict):
        try:
            set_system_proxy(True, port=HTTP_PORT)
        except Exception as e:
            self._set_status(f"خطا در تنظیم پروکسی: {e}", is_error=True)
            self._safe_disconnect()
            return
        self.connected_key = self._server_key(cfg)
        self._update_connection_colors()
        self._begin_session(cfg)
        self._start_monitor()
        self._set_status("متصل — پروکسی سیستم روشن شد")

    def on_core_error(self, msg: str):
        print("\n" + "=" * 50)
        print("CORE ERROR LOG:")
        print(msg)
        print("=" * 50 + "\n")

        display_msg = msg
        if "vless without TLS" in msg or "without TLS or other encryption" in msg:
            display_msg = ("این سرور از VLESS بدون رمزنگاری (TLS/Reality) استفاده می‌کند و آدرس آن هم IP است.\n"
                           "نسخه‌های جدید هسته Xray به دلایل امنیتی اجازه اتصال به IP بدون TLS را نمی‌دهند.\n"
                           "لطفاً از سروری با پروتکل VLESS+TLS یا VMess یا Trojan استفاده کنید.")
        elif "Only one usage of each socket address" in msg or "address already in use" in msg:
            display_msg = ("پورت‌های برنامه توسط یک پردازش قبلی اشغال شده است.\n"
                           "برنامه به صورت خودکار سعی می‌کند پردازش‌های قبلی را ببندد، لطفاً دوباره روی «اتصال» کلیک کنید.")

        self._set_status("خطا در اتصال. برای مشاهده جزئیات، پنجره خطا یا کنسول را بررسی کنید.", is_error=True)
        self._safe_disconnect()
        self._show_error_dialog("خطای اتصال Xray", display_msg)

    # ---------- Disconnect ----------
    def on_disconnect(self):
        self._safe_disconnect()
        self._set_status("قطع شد — مصرف نشست ذخیره شد")

    def _safe_disconnect(self):
        self._finalize_session()
        try:
            restore_backup()
        except Exception as e:
            print(f"[disconnect] restore failed: {e}")
        self._stop_monitor()
        if self.core_thread is not None:
            try:
                self.core_thread.stop()
                self.core_thread.wait(3000)
            except Exception:
                pass
            self.core_thread = None
        self.connected_key = None
        self._update_connection_colors()
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)

    # ---------- Close ----------
    def closeEvent(self, event):
        self._safe_disconnect()
        if self.test_thread is not None:
            self.test_thread.cancel()
            self.test_thread.wait(10000)
            self.test_thread = None
        if self.one_thread is not None:
            self.one_thread.wait(10000)
            self.one_thread = None
        if self.flag_prefetcher is not None:
            self.flag_prefetcher.wait(5000)
            self.flag_prefetcher = None
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.LeftToRight)

    w = MainWindow()
    app.aboutToQuit.connect(w._safe_disconnect)
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()