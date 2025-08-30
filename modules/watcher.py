# modules/watcher.py
"""
Watcher module (Qt Edition).

Receives runtime SFTP configuration from the UI so connection
details can be provided at launch instead of relying solely on
static settings.

- Drive: list & download to local temp
- SFTP: upload to auto path based on username
- Drive: move to Archive on success
"""

import os
import time
import logging
from typing import Optional, Dict, Any, List

from modules import drive_handler
from modules.sftp_handler import SFTPHandler
from config import settings

logger = logging.getLogger("SigmaApp")


class Watcher:
    """Runner used by the UI."""
    def __init__(self, drive_service=None, sftp_conf: Optional[Dict[str, Any]] = None, temp_dir: Optional[str] = None):
        self.drive_service = drive_service or drive_handler.get_drive_service()
        self.sftp_conf = sftp_conf or {}
        self.temp_dir = temp_dir or settings.TEMP_DOWNLOAD_DIR
        os.makedirs(self.temp_dir, exist_ok=True)

    def _filter_allowed(self, name: str) -> bool:
        if not settings.ALLOWED_EXTENSIONS:
            return True
        ext = os.path.splitext(name)[1].lstrip(".").lower()
        return ext in {e.lower() for e in settings.ALLOWED_EXTENSIONS}

    def run_once(self, drive_folder_id: Optional[str] = None, archive_folder_name: Optional[str] = None):
        folder_id = (drive_folder_id or settings.DRIVE_FOLDER_ID or "").strip()
        if not folder_id:
            logger.warning("Watcher: Drive Folder ID is empty. Skipping.")
            return

        logger.info("Watcher: checking Drive for new files...")
        files = drive_handler.download_all_from_folder(
            folder_id=folder_id,
            dest_dir=self.temp_dir,
            service=self.drive_service,
            delete_after_download=False
        )

        files_ok: List[Dict[str, Any]] = []
        for f in files:
            if f.get("status") != "OK":
                logger.warning(f"Skipping errored file {f.get('name')}: {f.get('message')}")
                continue
            if not self._filter_allowed(f.get("name", "")):
                logger.info(f"Skipping disallowed extension: {f.get('name')}")
                continue
            if getattr(settings, "MAX_FILE_SIZE_MB", 0):
                try:
                    sz_mb = (os.path.getsize(f["path"]) / (1024 * 1024))
                    if sz_mb > settings.MAX_FILE_SIZE_MB:
                        logger.warning(f"Skipping {f['name']} — size {sz_mb:.2f}MB > limit {settings.MAX_FILE_SIZE_MB}MB")
                        continue
                except Exception as e:
                    logger.warning(f"Cannot stat size for {f['path']}: {e}")
            files_ok.append(f)

        if not files_ok:
            logger.info("Watcher: no new files.")
            return

        # SFTP once per cycle
        sftp = SFTPHandler(
            host=self.sftp_conf.get("host", settings.SFTP_HOST),
            port=int(self.sftp_conf.get("port", settings.SFTP_PORT or 22)),
            username=self.sftp_conf.get("username", settings.SFTP_USERNAME),
            password=self.sftp_conf.get("password") or None,
            key_file=self.sftp_conf.get("key_file") or None,
        )
        sftp.connect()
        try:
            for f in files_ok:
                local_path = f["path"]
                try:
                    sftp.upload_to_auto_dir(local_path)
                    moved = drive_handler.move_file_to_archive(
                        f["id"], self.drive_service, archive_folder_name=archive_folder_name or settings.ARCHIVE_FOLDER_NAME
                    )
                    if moved:
                        logger.info(f"Drive: moved '{f['name']}' to Archive.")
                    else:
                        logger.warning(f"Drive: could not move '{f['name']}' to Archive.")

                    try:
                        if os.path.exists(local_path):
                            os.remove(local_path)
                            logger.info(f"Temp: removed {local_path}")
                    except Exception as e:
                        logger.exception(f"Temp: failed to remove {local_path}: {e}")

                except Exception as e:
                    logger.exception(f"Upload failed for {f['name']}: {e}")

        finally:
            sftp.close()

    def start_loop(self, drive_folder_id: Optional[str] = None, stop_flag=None, poll_interval: Optional[int] = None):
        interval = int(poll_interval or settings.POLL_INTERVAL or 30)
        logger.info("Watcher: loop started.")
        while True:
            if stop_flag and stop_flag():
                logger.info("Watcher: stop requested. exiting loop.")
                break
            try:
                self.run_once(drive_folder_id=drive_folder_id)
            except Exception:
                logger.exception("Watcher: cycle failed with exception.")
            for _ in range(interval):
                if stop_flag and stop_flag():
                    break
                time.sleep(1)
        logger.info("Watcher: loop stopped.")
