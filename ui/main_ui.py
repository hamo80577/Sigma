# ui/main_ui.py
import threading
import time
import os
import logging
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# imports from project modules
from modules import sftp_handler, drive_handler
from modules import watcher as watcher_module
from config import settings
from config.logger import logger

from .animations import Blinker


class TextHandler(logging.Handler):
    """Logging handler that writes into a Tkinter Text widget (thread-safe via after)."""
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    def emit(self, record):
        try:
            msg = self.format(record)
            def append():
                self.text_widget.config(state="normal")
                self.text_widget.insert("end", msg + "\n")
                self.text_widget.see("end")
                self.text_widget.config(state="disabled")
            self.text_widget.after(0, append)
        except Exception:
            pass


class MainUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Sigma S1 — Drive → SFTP")
        self.geometry("920x640")
        self.resizable(True, True)

        # internal state
        self.watcher_thread = None
        self.stop_event = None
        self.bg_watcher = None  # watcher_module.Watcher instance
        self.blinker = None

        # default service account path
        default_sa = getattr(drive_handler, "DEFAULT_SA_PATH", os.path.join(os.path.dirname(__file__), "..", "sigma-service-account.json"))
        self.service_account_path = tk.StringVar(value=default_sa)
        self.drive_folder_id_var = tk.StringVar(value=getattr(settings, "DRIVE_FOLDER_ID", ""))
        # SFTP fields
        self.sftp_host_var = tk.StringVar(value=getattr(settings, "SFTP_HOST", ""))
        self.sftp_port_var = tk.IntVar(value=getattr(settings, "SFTP_PORT", 22))
        self.sftp_user_var = tk.StringVar(value=getattr(settings, "SFTP_USERNAME", ""))
        self.sftp_pass_var = tk.StringVar(value=getattr(settings, "SFTP_PASSWORD", ""))
        self.sftp_key_var = tk.StringVar(value=getattr(settings, "SFTP_KEY_FILE", "") or "")

        self._build_ui()
        # wire logger -> text widget
        self.text_handler = TextHandler(self.log_text)
        logger.addHandler(self.text_handler)
        logger.setLevel(logging.INFO)

    def _build_ui(self):
        pad = 8
        frm_top = ttk.Frame(self)
        frm_top.pack(side="top", fill="x", padx=pad, pady=pad)

        # Drive config
        drive_frame = ttk.LabelFrame(frm_top, text="Google Drive")
        drive_frame.pack(side="left", fill="x", expand=True, padx=pad, pady=pad)

        ttk.Label(drive_frame, text="Service account JSON:").grid(row=0, column=0, sticky="w")
        sa_entry = ttk.Entry(drive_frame, textvariable=self.service_account_path, width=50)
        sa_entry.grid(row=0, column=1, sticky="w", padx=(4, 4))
        ttk.Button(drive_frame, text="Browse", command=self.browse_service_account).grid(row=0, column=2)

        ttk.Label(drive_frame, text="Drive Folder ID:").grid(row=1, column=0, sticky="w", pady=(6,0))
        ttk.Entry(drive_frame, textvariable=self.drive_folder_id_var, width=50).grid(row=1, column=1, columnspan=2, sticky="w", pady=(6,0))

        # SFTP config
        sftp_frame = ttk.LabelFrame(frm_top, text="SFTP")
        sftp_frame.pack(side="right", fill="x", expand=True, padx=pad, pady=pad)

        ttk.Label(sftp_frame, text="Host:").grid(row=0, column=0, sticky="w")
        ttk.Entry(sftp_frame, textvariable=self.sftp_host_var, width=30).grid(row=0, column=1, sticky="w")
        ttk.Label(sftp_frame, text="Port:").grid(row=0, column=2, sticky="w", padx=(10,0))
        ttk.Entry(sftp_frame, textvariable=self.sftp_port_var, width=6).grid(row=0, column=3, sticky="w")

        ttk.Label(sftp_frame, text="Username:").grid(row=1, column=0, sticky="w", pady=(6,0))
        ttk.Entry(sftp_frame, textvariable=self.sftp_user_var, width=30).grid(row=1, column=1, sticky="w", pady=(6,0))
        ttk.Label(sftp_frame, text="Password / Key:").grid(row=2, column=0, sticky="w", pady=(6,0))
        ttk.Entry(sftp_frame, textvariable=self.sftp_pass_var, show="*", width=30).grid(row=2, column=1, sticky="w", pady=(6,0))
        ttk.Entry(sftp_frame, textvariable=self.sftp_key_var, width=30).grid(row=3, column=1, sticky="w", pady=(6,0))
        ttk.Button(sftp_frame, text="Browse Key", command=self.browse_sftp_key).grid(row=3, column=2, sticky="w")

        # Controls
        ctrl_frame = ttk.Frame(self)
        ctrl_frame.pack(fill="x", padx=pad, pady=(0,pad))

        self.conn_label = ttk.Label(ctrl_frame, text="Connection: ⬤", font=("Segoe UI", 10, "bold"))
        self.conn_label.pack(side="left", padx=(2,12))
        self.blinker = Blinker(self.conn_label)

        ttk.Button(ctrl_frame, text="Test SFTP", command=self.test_sftp).pack(side="left", padx=4)
        ttk.Button(ctrl_frame, text="Run once now", command=self.run_once).pack(side="left", padx=4)
        self.start_btn = ttk.Button(ctrl_frame, text="Start watcher", command=self.start_watcher)
        self.start_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(ctrl_frame, text="Stop watcher", command=self.stop_watcher, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        ttk.Button(ctrl_frame, text="Open latest log", command=self.open_latest_log).pack(side="right", padx=4)

        # Log area
        log_frame = ttk.LabelFrame(self, text="Log")
        log_frame.pack(fill="both", expand=True, padx=pad, pady=pad)

        self.log_text = tk.Text(log_frame, state="disabled", wrap="none", height=20)
        self.log_text.pack(fill="both", expand=True, side="left")
        # add a simple vertical scrollbar
        vs = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        vs.pack(side="right", fill="y")
        self.log_text['yscrollcommand'] = vs.set

    def browse_service_account(self):
        path = filedialog.askopenfilename(title="Select service account JSON", filetypes=[("JSON files","*.json"),("All files","*.*")])
        if path:
            self.service_account_path.set(path)

    def browse_sftp_key(self):
        path = filedialog.askopenfilename(title="Select private key file (or Cancel)", filetypes=[("Key files","*.*")])
        if path:
            self.sftp_key_var.set(path)

    def test_sftp(self):
        host = self.sftp_host_var.get().strip()
        port = int(self.sftp_port_var.get() or 22)
        user = self.sftp_user_var.get().strip()
        pwd = self.sftp_pass_var.get().strip() or None
        key = self.sftp_key_var.get().strip() or None

        if not host or not user:
            messagebox.showwarning("Missing", "Please provide SFTP host and username.")
            return

        self.set_conn_state("testing")

        def _do_test():
            try:
                s = sftp_handler.SFTPHandler(host=host, port=port, username=user, password=pwd, key_file=key)
                s.connect()
                logger.info("[UI] SFTP test connection OK")
                s.close()
                self.set_conn_state("ok")
            except Exception as e:
                logger.exception("SFTP test error: %s", e)
                self.set_conn_state("failed")

        threading.Thread(target=_do_test, daemon=True).start()

    def set_conn_state(self, state):
        """Update connection indicator (state: testing/ok/failed/idle)"""
        # run on UI thread
        def _update():
            if state == "testing":
                self.conn_label.config(text="Connection: ◐ Testing...", foreground="orange")
                self.blinker.start()
            elif state == "ok":
                self.conn_label.config(text="Connection: ● Connected", foreground="green")
                self.blinker.stop()
            elif state == "failed":
                self.conn_label.config(text="Connection: ● Failed", foreground="red")
                self.blinker.stop()
            else:
                self.conn_label.config(text="Connection: ● Idle", foreground="black")
                self.blinker.stop()
        self.after(0, _update)

    def run_once(self):
        """Run watcher.run_once synchronously (single cycle)."""
        try:
            logger.info("[UI] Running single watcher cycle...")
            # prepare service object using selected SA path
            sa = self.service_account_path.get().strip() or None
            try:
                svc = drive_handler.get_drive_service(service_account_file=sa) if sa else drive_handler.get_drive_service()
            except Exception as e:
                logger.exception("Drive auth failed: %s", e)
                messagebox.showerror("Drive auth", f"Failed to authenticate to Drive: {e}")
                return

            w = watcher_module.Watcher()
            w.drive_service = svc  # override service object
            w.run_once()
            logger.info("[UI] Single run finished.")
        except Exception as e:
            logger.exception("Run once failed: %s", e)

    def start_watcher(self):
        if self.watcher_thread and self.watcher_thread.is_alive():
            messagebox.showinfo("Watcher", "Watcher already running.")
            return

        # build watcher instance
        sa = self.service_account_path.get().strip() or None
        try:
            svc = drive_handler.get_drive_service(service_account_file=sa) if sa else drive_handler.get_drive_service()
        except Exception as e:
            logger.exception("Drive auth failed: %s", e)
            messagebox.showerror("Drive auth", f"Failed to authenticate to Drive: {e}")
            return

        self.bg_watcher = watcher_module.Watcher()
        self.bg_watcher.drive_service = svc  # override default auth

        self.stop_event = threading.Event()

        def _loop():
            logger.info("[UI] Watcher background thread started.")
            # signal UI connected state
            self.set_conn_state("ok")
            poll = getattr(settings, "POLL_INTERVAL", 30)
            while not self.stop_event.is_set():
                try:
                    self.bg_watcher.run_once()
                except Exception:
                    logger.exception("Background watcher run_once error")
                # sleep in small steps so we can stop quickly
                for _ in range(max(1, int(poll))):
                    if self.stop_event.is_set():
                        break
                    time.sleep(1)
            logger.info("[UI] Watcher background thread stopping.")
            self.set_conn_state("idle")

        self.watcher_thread = threading.Thread(target=_loop, daemon=True)
        self.watcher_thread.start()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")

    def stop_watcher(self):
        if self.stop_event:
            self.stop_event.set()
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        logger.info("[UI] Stop signal sent to watcher thread.")

    def open_latest_log(self):
        # try to open today's log file created by config/logger.py
        try:
            logs_dir = os.path.join(os.getcwd(), "logs")
            if not os.path.isdir(logs_dir):
                messagebox.showinfo("Logs", "No logs folder found.")
                return
            files = sorted([f for f in os.listdir(logs_dir) if f.startswith("app_")], reverse=True)
            if not files:
                messagebox.showinfo("Logs", "No log files found.")
                return
            path = os.path.join(logs_dir, files[0])
            # open with default program
            try:
                if os.name == "nt":
                    os.startfile(path)
                else:
                    import subprocess
                    subprocess.Popen(["xdg-open", path])
            except Exception:
                messagebox.showinfo("Log path", f"Log file: {path}")
        except Exception as e:
            logger.exception("Failed to open log: %s", e)


if __name__ == "__main__":
    app = MainUI()
    app.mainloop()
