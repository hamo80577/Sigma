# qt_main.py
# Sigma Desktop - PySide6 UI (no popups, colored log, left logo + right lamps, unified theme)
import os
import sys
import logging
from typing import Optional, Dict, Any

from PySide6.QtCore import Qt, QThread, QObject, Signal, Slot
from PySide6.QtGui import QTextCursor, QPixmap, QMovie
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QTextEdit, QSpinBox, QComboBox, QFrame,
    QCheckBox, QScrollArea, QSplitter, QSizePolicy
)

from config import settings
from config.logger import logger
from modules import drive_handler
from modules.watcher import Watcher
from modules.sftp_handler import SFTPHandler
from profiles_store import ProfilesStore


# ---------------- Theme ----------------
TOP_BAR_H = 48
CLR_BG = "#0F1115"
CLR_TXT = "#E5E7EB"
CLR_PANEL = "#151922"
CLR_BORDER = "#1F2430"
CLR_PRIMARY = "#7C5CFC"
CLR_PRIMARY_H = "#8B6CFF"
CLR_MUTED = "#9CA3AF"

# lamps
CLR_GRAY = "#6B7280"
CLR_ORANGE = "#F59E0B"
CLR_GREEN = "#10B981"
CLR_RED = "#EF4444"
CLR_BLUE = "#3B82F6"

# -------- Tiny Lamp widget (status indicator) --------
class Lamp(QWidget):
    def __init__(self, text: str, color: str = CLR_GRAY, parent=None):
        super().__init__(parent)
        self._lbl = QLabel(text)
        self._lbl.setStyleSheet(f"color:{CLR_TXT};")
        self._dot = QWidget()
        self._dot.setFixedSize(14, 14)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self._dot)
        lay.addWidget(self._lbl)
        self.set_color(color)
        self.setFixedHeight(18)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def set_color(self, hex_color: str):
        self._dot.setStyleSheet(f"border-radius:7px; background:{hex_color};")


# -------- Logging → Qt bridge --------
class LogEmitter(QObject):
    sig = Signal(str)


class QtLogHandler(logging.Handler):
    def __init__(self, emitter: LogEmitter):
        super().__init__()
        self.emitter = emitter
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    def emit(self, record):
        try:
            msg = self.format(record)
            self.emitter.sig.emit(msg)
        except Exception:
            pass


# -------- Worker (QThread) --------
class WatcherWorker(QObject):
    finished = Signal()
    status = Signal(str)  # connecting | watching | error

    def __init__(self, drive_sa_path: Optional[str], drive_folder_id: str, sftp_conf: Dict[str, Any], poll_interval: int):
        super().__init__()
        self.drive_sa_path = drive_sa_path
        self.drive_folder_id = drive_folder_id
        self.sftp_conf = sftp_conf
        self.poll_interval = poll_interval
        self._stop = False

    @Slot()
    def start(self):
        try:
            self.status.emit("connecting")
            svc = drive_handler.get_drive_service(service_account_file=self.drive_sa_path) if self.drive_sa_path else drive_handler.get_drive_service()
            w = Watcher(drive_service=svc, sftp_conf=self.sftp_conf, temp_dir=settings.TEMP_DOWNLOAD_DIR)

            def _stop_flag():
                return self._stop

            self.status.emit("watching")
            w.start_loop(drive_folder_id=self.drive_folder_id, stop_flag=_stop_flag, poll_interval=self.poll_interval)
        except Exception as e:
            logger.exception("Watcher thread error: %s", e)
            self.status.emit("error")
        finally:
            self.finished.emit()

    @Slot()
    def stop(self):
        self._stop = True


# -------- Main Window --------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sigma S1 — Drive → SFTP (Qt)")
        self.resize(1080, 720)

        # profiles
        self.store = ProfilesStore()
        self.current_profile_name = None

        # state
        self.thread: Optional[QThread] = None
        self.worker: Optional[WatcherWorker] = None

        # log bridge
        self.log_emitter = LogEmitter()
        self.log_emitter.sig.connect(self._append_log)
        self.qt_log_handler = QtLogHandler(self.log_emitter)
        logging.getLogger().addHandler(self.qt_log_handler)
        logging.getLogger().setLevel(logging.INFO)

        # status lamps
        self.lamp_drive = Lamp("Drive", CLR_GRAY)
        self.lamp_sftp = Lamp("SFTP", CLR_GRAY)
        self.lamp_watcher = Lamp("Watcher", CLR_GRAY)

        # logo (static + loading movie)
        base_dir = os.path.dirname(__file__)
        self.logo_png = os.path.join(base_dir, "Logo.png")
        self.logo_gif = os.path.join(base_dir, "logo_loading.gif")
        self.logo_lbl = QLabel()
        self.logo_lbl.setFixedHeight(TOP_BAR_H-8)
        self.logo_lbl.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._movie: Optional[QMovie] = None
        self._set_logo_static()

        self._build_ui()
        self._apply_dark_qss()
        self._load_profiles_into_combo()

    # ---------- UI ----------
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(8)

        # Top bar: logo left + lamps right
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(14)

        top_bar.addWidget(self.logo_lbl)
        top_bar.addStretch(1)

        # group lamps right
        lamps_row = QHBoxLayout()
        lamps_row.setSpacing(14)
        lamps_row.addWidget(self.lamp_drive)
        lamps_row.addWidget(self.lamp_sftp)
        lamps_row.addWidget(self.lamp_watcher)
        lamps_wrap = QWidget(); lamps_wrap.setLayout(lamps_row)
        top_bar.addWidget(lamps_wrap)

        wrap_top = QWidget()
        wrap_top.setLayout(top_bar)
        wrap_top.setFixedHeight(TOP_BAR_H)
        wrap_top.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root_layout.addWidget(wrap_top)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ====== Sidebar (scrollable) ======
        side_layout = QVBoxLayout()
        side_layout.setSpacing(8)
        side_layout.setContentsMargins(8, 8, 8, 8)

        # Profiles
        self.combo_profiles = QComboBox()
        self.combo_profiles.currentIndexChanged.connect(self._on_profile_selected)
        side_layout.addWidget(QLabel("Profiles"))
        side_layout.addWidget(self.combo_profiles)

        btn_new = QPushButton("New"); btn_new.clicked.connect(self._new_profile)
        btn_save = QPushButton("Save"); btn_save.clicked.connect(self._save_profile)
        btn_delete = QPushButton("Delete"); btn_delete.clicked.connect(self._delete_profile)
        row_profiles = QHBoxLayout(); row_profiles.addWidget(btn_new); row_profiles.addWidget(btn_save); row_profiles.addWidget(btn_delete)
        row_profiles_w = QWidget(); row_profiles_w.setLayout(row_profiles)
        side_layout.addWidget(row_profiles_w)

        side_layout.addWidget(self._hline())

        # Drive
        side_layout.addWidget(QLabel("Service Account JSON"))
        default_sa = os.path.normpath(os.path.join(os.path.dirname(__file__), "sigma-service-account.json"))
        self.ed_sa = QLineEdit(default_sa if os.path.exists(default_sa) else "")
        btn_browse_sa = QPushButton("Browse"); btn_browse_sa.clicked.connect(self._browse_sa)
        row_sa = QHBoxLayout(); row_sa.addWidget(self.ed_sa); row_sa.addWidget(btn_browse_sa)
        wrap_sa = QWidget(); wrap_sa.setLayout(row_sa)
        side_layout.addWidget(wrap_sa)

        side_layout.addWidget(QLabel("Drive Folder ID"))
        self.ed_drive_id = QLineEdit(settings.DRIVE_FOLDER_ID or "")
        side_layout.addWidget(self.ed_drive_id)

        btn_test_drive = QPushButton("Test Drive"); btn_test_drive.clicked.connect(self._test_drive)
        side_layout.addWidget(btn_test_drive)

        side_layout.addWidget(self._hline())

        # SFTP
        side_layout.addWidget(QLabel("SFTP Host"))
        self.ed_host = QLineEdit(settings.SFTP_HOST or "")
        side_layout.addWidget(self.ed_host)

        row_port_user = QHBoxLayout()
        self.sp_port = QSpinBox(); self.sp_port.setRange(1, 65535); self.sp_port.setValue(int(settings.SFTP_PORT or 22))
        self.ed_user = QLineEdit(settings.SFTP_USERNAME or "")
        row_port_user.addWidget(QLabel("Port")); row_port_user.addWidget(self.sp_port)
        row_port_user.addWidget(QLabel("User")); row_port_user.addWidget(self.ed_user)
        wrap_pu = QWidget(); wrap_pu.setLayout(row_port_user)
        side_layout.addWidget(wrap_pu)

        self.ed_pass = QLineEdit(settings.SFTP_PASSWORD or ""); self.ed_pass.setEchoMode(QLineEdit.Password)
        side_layout.addWidget(QLabel("Password (or leave empty if Key)"))
        side_layout.addWidget(self.ed_pass)

        row_key = QHBoxLayout()
        self.ed_key = QLineEdit(settings.SFTP_KEY_FILE or "")
        btn_browse_key = QPushButton("Browse Key"); btn_browse_key.clicked.connect(self._browse_key)
        row_key.addWidget(self.ed_key); row_key.addWidget(btn_browse_key)
        wrap_key = QWidget(); wrap_key.setLayout(row_key)
        side_layout.addWidget(QLabel("Private Key (optional)"))
        side_layout.addWidget(wrap_key)

        # Hint (auto path)
        hint = QLabel("Remote Path: auto → /vendor-automation-sftp-storage-live-me-1/home/{User}/catalog")
        hint.setStyleSheet(f"color:{CLR_MUTED}; font-size:11px;")
        side_layout.addWidget(hint)

        btn_test_sftp = QPushButton("Test SFTP"); btn_test_sftp.clicked.connect(self._test_sftp)
        side_layout.addWidget(btn_test_sftp)

        side_layout.addWidget(self._hline())

        # Watcher controls
        row_watch = QHBoxLayout()
        self.btn_run_once = QPushButton("Run Once")
        self.btn_start = QPushButton("Start")
        self.btn_stop = QPushButton("Stop"); self.btn_stop.setEnabled(False)
        row_watch.addWidget(self.btn_run_once); row_watch.addWidget(self.btn_start); row_watch.addWidget(self.btn_stop)
        wrap_watch = QWidget(); wrap_watch.setLayout(row_watch)
        side_layout.addWidget(wrap_watch)

        row_poll = QHBoxLayout()
        self.sp_poll = QSpinBox(); self.sp_poll.setRange(3, 3600); self.sp_poll.setValue(int(settings.POLL_INTERVAL or 30))
        row_poll.addWidget(QLabel("Poll (s)")); row_poll.addWidget(self.sp_poll)
        wrap_poll = QWidget(); wrap_poll.setLayout(row_poll)
        side_layout.addWidget(wrap_poll)

        self.chk_auto_scroll = QCheckBox("Auto-scroll log"); self.chk_auto_scroll.setChecked(True)
        side_layout.addWidget(self.chk_auto_scroll)

        side_layout.addStretch()

        side_w = QWidget(); side_w.setLayout(side_layout)
        side_w.setMinimumWidth(320)
        side_w.setMaximumWidth(460)

        side_scroll = QScrollArea()
        side_scroll.setWidget(side_w)
        side_scroll.setWidgetResizable(True)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        side_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        side_scroll.setFrameShape(QFrame.NoFrame)
        side_scroll.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        # ====== Center (log area) ======
        center_layout = QVBoxLayout()
        center_layout.setContentsMargins(8, 8, 8, 8); center_layout.setSpacing(8)

        center_layout.addWidget(QLabel("Log"))
        self.txt_log = QTextEdit(); self.txt_log.setReadOnly(True)
        self.txt_log.setPlaceholderText("Logs will appear here...")
        self.txt_log.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        center_layout.addWidget(self.txt_log)

        row_log = QHBoxLayout()
        btn_clear = QPushButton("Clear"); btn_clear.clicked.connect(lambda: self.txt_log.clear())
        btn_export = QPushButton("Export Log"); btn_export.clicked.connect(self._export_log)
        row_log.addWidget(btn_clear); row_log.addWidget(btn_export)
        row_lw = QWidget(); row_lw.setLayout(row_log)
        center_layout.addWidget(row_lw)

        center_w = QWidget(); center_w.setLayout(center_layout)

        splitter.addWidget(side_scroll)
        splitter.addWidget(center_w)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        root_layout.addWidget(splitter, 1)

    def _hline(self):
        line = QFrame(); line.setFrameShape(QFrame.HLine); line.setFrameShadow(QFrame.Sunken)
        return line

    # ---------- Logo helpers ----------
    def _set_logo_static(self):
        if os.path.exists(self.logo_png):
            pix = QPixmap(self.logo_png)
            self.logo_lbl.setPixmap(pix.scaledToHeight(TOP_BAR_H-8, Qt.SmoothTransformation))
        else:
            self.logo_lbl.setText("Sigma S1")
            self.logo_lbl.setStyleSheet("font-size:16px; font-weight:600; color:#E5E7EB;")

    def _set_logo_loading(self):
        if os.path.exists(self.logo_gif):
            self._movie = QMovie(self.logo_gif)
            self.logo_lbl.setMovie(self._movie)
            self._movie.start()
        else:
            self._set_logo_static()

    def _stop_loading_logo(self):
        if self._movie:
            self._movie.stop()
            self._movie = None
        self._set_logo_static()

    # ---------- Actions ----------
    def _browse_sa(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Service Account JSON", os.path.dirname(self.ed_sa.text()), "JSON (*.json);;All Files (*)")
        if path:
            self.ed_sa.setText(path)

    def _browse_key(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Private Key", os.path.dirname(self.ed_key.text()), "All Files (*)")
        if path:
            self.ed_key.setText(path)

    def _test_drive(self):
        # بدون Popups: كله في اللوج + لمبة
        try:
            self.lamp_drive.set_color(CLR_ORANGE)  # testing
            logger.info("[UI] Testing Drive auth/list ...")
            svc = drive_handler.get_drive_service(service_account_file=(self.ed_sa.text().strip() or None))
            fid = self.ed_drive_id.text().strip()
            if not fid:
                logger.info("[UI] Drive auth OK. No folder ID provided.")
                self.lamp_drive.set_color(CLR_GREEN)
                return
            files = drive_handler.list_files_in_folder(fid, svc, page_size=3)
            logger.info(f"[UI] Drive list OK. Items in folder: {len(files)}")
            self.lamp_drive.set_color(CLR_GREEN)
        except Exception as e:
            logger.exception(f"[UI] Drive test failed: {e}")
            self.lamp_drive.set_color(CLR_RED)

    def _test_sftp(self):
        try:
            self.lamp_sftp.set_color(CLR_ORANGE)
            logger.info("[UI] Testing SFTP connection ...")
            client = SFTPHandler(
                host=self.ed_host.text().strip(),
                port=int(self.sp_port.value()),
                username=self.ed_user.text().strip(),
                password=(self.ed_pass.text().strip() or None),
                key_file=(self.ed_key.text().strip() or None),
            )
            client.connect()
            auto_dir = client.get_auto_remote_dir()
            client.makedirs(auto_dir)
            client.close()
            logger.info(f"[UI] SFTP OK. Auto path ready: {auto_dir}")
            self.lamp_sftp.set_color(CLR_GREEN)
        except Exception as e:
            logger.exception(f"[UI] SFTP test failed: {e}")
            self.lamp_sftp.set_color(CLR_RED)

    def _sftp_conf(self) -> Dict[str, Any]:
        return {
            "host": self.ed_host.text().strip(),
            "port": int(self.sp_port.value()),
            "username": self.ed_user.text().strip(),
            "password": (self.ed_pass.text().strip() or None),
            "key_file": (self.ed_key.text().strip() or None),
        }

    def _run_once_async(self):
        def job():
            try:
                logger.info("[UI] Single run started.")
                svc = drive_handler.get_drive_service(service_account_file=(self.ed_sa.text().strip() or None))
                w = Watcher(drive_service=svc, sftp_conf=self._sftp_conf(), temp_dir=settings.TEMP_DOWNLOAD_DIR)
                self._set_logo_loading()
                w.run_once(drive_folder_id=self.ed_drive_id.text().strip(), archive_folder_name=settings.ARCHIVE_FOLDER_NAME)
                logger.info("[UI] Single run finished.")
            except Exception as e:
                logger.exception("Run once failed: %s", e)
            finally:
                self._stop_loading_logo()
        import threading
        threading.Thread(target=job, daemon=True).start()

    def _start_watcher(self):
        if self.thread and self.thread.isRunning():
            logger.info("[UI] Watcher already running.")
            return

        sftp_conf = self._sftp_conf()
        if not sftp_conf["host"] or not sftp_conf["username"]:
            logger.warning("[UI] Please fill SFTP host & username.")
            return

        self.thread = QThread()
        self.worker = WatcherWorker(
            drive_sa_path=(self.ed_sa.text().strip() or None),
            drive_folder_id=self.ed_drive_id.text().strip(),
            sftp_conf=sftp_conf,
            poll_interval=int(self.sp_poll.value())
        )
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.start)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.status.connect(self._on_status)

        self.thread.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.lamp_watcher.set_color(CLR_ORANGE)
        self._set_logo_loading()
        logger.info("[UI] Watcher started.")

    def _stop_watcher(self):
        if self.worker:
            self.worker.stop()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.lamp_watcher.set_color(CLR_GRAY)
        self._stop_loading_logo()
        logger.info("[UI] Stop requested.")

    def _on_status(self, s: str):
        if s == "watching":
            self.lamp_watcher.set_color(CLR_GREEN)
            self._set_logo_loading()
        elif s in ("error",):
            self.lamp_watcher.set_color(CLR_RED)
            self._stop_loading_logo()
        elif s in ("connecting",):
            self.lamp_watcher.set_color(CLR_ORANGE)
            self._set_logo_loading()
        else:
            self.lamp_watcher.set_color(CLR_GRAY)
            self._stop_loading_logo()
        logger.info(f"[UI] status: {s}")

    # ---------- Profiles ----------
    def _load_profiles_into_combo(self):
        self.combo_profiles.blockSignals(True)
        self.combo_profiles.clear()
        names = self.store.list_names()
        self.combo_profiles.addItem("-- Select profile --")
        for n in names:
            self.combo_profiles.addItem(n)
        self.combo_profiles.blockSignals(False)

    def _on_profile_selected(self, idx: int):
        if idx <= 0:
            return
        name = self.combo_profiles.currentText()
        prof = self.store.load(name)
        if not prof:
            return
        self.current_profile_name = name

        self.ed_host.setText(prof.get("host", ""))
        self.sp_port.setValue(int(prof.get("port", 22)))
        self.ed_user.setText(prof.get("username", ""))
        self.ed_pass.setText(self.store.decrypt(prof.get("password_enc")) or "")
        self.ed_key.setText(prof.get("key_file", ""))

        self.ed_drive_id.setText(prof.get("drive_folder_id", ""))
        if prof.get("service_account_path"):
            self.ed_sa.setText(prof.get("service_account_path"))

        logger.info(f"[UI] Profile '{name}' loaded.")

    def _new_profile(self):
        self.current_profile_name = None
        self.combo_profiles.setCurrentIndex(0)
        self.ed_host.clear(); self.sp_port.setValue(22); self.ed_user.clear()
        self.ed_pass.clear(); self.ed_key.clear()
        logger.info("[UI] New profile fields cleared.")

    def _save_profile(self):
        name = "Profile"
        # حفظ باسم سريع لو عايز – ممكن تضيف Dialog لاحقًا
        data = {
            "host": self.ed_host.text().strip(),
            "port": int(self.sp_port.value()),
            "username": self.ed_user.text().strip(),
            "password_enc": self.store.encrypt(self.ed_pass.text().strip()),
            "key_file": self.ed_key.text().strip(),
            "drive_folder_id": self.ed_drive_id.text().strip(),
            "service_account_path": self.ed_sa.text().strip(),
        }
        self.store.save(name.strip(), data)
        self._load_profiles_into_combo()
        self.current_profile_name = name.strip()
        self.combo_profiles.setCurrentText(self.current_profile_name)
        logger.info(f"[UI] Profile '{self.current_profile_name}' saved.")

    def _delete_profile(self):
        if not self.current_profile_name:
            logger.info("[UI] No profile selected.")
            return
        self.store.delete(self.current_profile_name)
        self.current_profile_name = None
        self._load_profiles_into_combo()
        self._new_profile()
        logger.info("[UI] Profile deleted.")

    # ---------- Logging ----------
    @Slot(str)
    def _append_log(self, text: str):
        # تلوين حسب المستوى
        line = text
        color = CLR_TXT
        if " [ERROR] " in line or " ERROR " in line:
            color = CLR_RED
        elif " [WARNING] " in line or " WARNING " in line or " WARN " in line:
            color = CLR_ORANGE
        elif " [INFO] " in line or " INFO " in line:
            color = CLR_BLUE
        elif " [DEBUG] " in line or " DEBUG " in line:
            color = CLR_MUTED
        elif " SFTP: upload OK" in line or "OK." in line:
            color = CLR_GREEN

        # إدراج HTML ملوّن
        safe = (line
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))
        self.txt_log.moveCursor(QTextCursor.End)
        self.txt_log.insertHtml(f'<span style="color:{color};">{safe}</span><br/>')
        if self.chk_auto_scroll.isChecked():
            self.txt_log.moveCursor(QTextCursor.End)

    def _export_log(self):
        # بدون Popups: نكتب دايركت لملف قياسي في الهوم
        path = os.path.expanduser("~/sigma_log.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.txt_log.toPlainText())
            logger.info(f"[UI] Log exported to {path}")
        except Exception as e:
            logger.exception(f"[UI] Export failed: {e}")

    # ---------- Style ----------
    def _apply_dark_qss(self):
        # توحيد نفس الألوان في كل الواجهة
        self.setStyleSheet(f"""
            QMainWindow {{ background: {CLR_BG}; color: {CLR_TXT}; }}
            QLabel {{ color: {CLR_TXT}; }}
            QLineEdit, QTextEdit, QSpinBox, QComboBox {{
                background: {CLR_PANEL}; color: {CLR_TXT};
                border: 1px solid {CLR_BORDER}; border-radius: 8px; padding: 6px;
            }}
            QPushButton {{
                background: {CLR_PRIMARY}; color: white; border: none; padding: 8px 12px; border-radius: 10px;
            }}
            QPushButton:hover {{ background: {CLR_PRIMARY_H}; }}
            QPushButton:disabled {{ background: #3a3f51; color: #999; }}
            QFrame[frameShape="4"] {{ color: {CLR_BORDER}; background: {CLR_BORDER}; max-height: 1px; }}
            QScrollBar:vertical {{ background: {CLR_BG}; width: 10px; }}
            QScrollBar::handle:vertical {{ background: #2A2F3A; min-height: 30px; border-radius: 4px; }}
            QScrollArea {{ background: transparent; border: none; }}
        """)


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
