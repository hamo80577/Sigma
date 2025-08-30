# modules/sftp_handler.py
import errno
import logging
import os
from typing import Optional

import paramiko

logger = logging.getLogger("SigmaApp")


class SFTPHandler:
    """
    SFTP helper:
      - connect/close
      - detect home (normalize("."))
      - build auto remote dir: /vendor-automation-sftp-storage-live-me-1/home/<username>/catalog
      - remap to real home if chrooted → <home>/catalog
      - makedirs
      - upload_to_auto_dir(local_path)
    """
    def __init__(self, host: str, port: int, username: str, password: Optional[str] = None, key_file: Optional[str] = None):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.key_file = key_file

        self._transport: Optional[paramiko.Transport] = None
        self._sftp: Optional[paramiko.SFTPClient] = None
        self._home: Optional[str] = None

    # ---------- connection ----------
    def connect(self):
        logger.info(f"SFTP: connecting to {self.host}:{self.port} as {self.username} ...")
        self._transport = paramiko.Transport((self.host, self.port))
        if self.key_file:
            pkey = paramiko.RSAKey.from_private_key_file(self.key_file)
            self._transport.connect(username=self.username, pkey=pkey)
        else:
            self._transport.connect(username=self.username, password=self.password)
        self._sftp = paramiko.SFTPClient.from_transport(self._transport)
        try:
            self._home = self._sftp.normalize(".")
        except Exception:
            self._home = None
        logger.info("SFTP: connected.")
        if self._home:
            logger.info(f"SFTP: home = {self._home}")
            try:
                listing = self._sftp.listdir(self._home)
                logger.info(f"SFTP: home listing = {listing}")
            except Exception as e:
                logger.warning(f"SFTP: cannot list home: {e}")

    def close(self):
        try:
            if self._sftp:
                self._sftp.close()
        finally:
            if self._transport:
                self._transport.close()
        logger.info("SFTP: disconnected.")

    # ---------- paths ----------
    def _aws_intended_dir(self) -> str:
        return f"/vendor-automation-sftp-storage-live-me-1/home/{self.username}/catalog"

    def get_auto_remote_dir(self) -> str:
        """
        Build effective remote dir:
         - intended: /vendor-.../home/<user>/catalog
         - if home known → remap to <home>/catalog (works with chroot)
        """
        intended = self._aws_intended_dir()
        if self._home:
            remapped = f"{self._home.rstrip('/')}/catalog"
            logger.info(f"SFTP: auto remote dir = {remapped} (remapped from AWS full path)")
            return remapped
        logger.info(f"SFTP: auto remote dir = {intended} (no remap)")
        return intended

    # ---------- mkdirs & upload ----------
    def makedirs(self, remote_dir: str):
        """Create remote directories recursively; ignore exists; bubble up EACCES."""
        if not remote_dir or remote_dir in ("/", ".", "~"):
            return
        parts = [p for p in remote_dir.strip("/").split("/") if p]
        absolute = remote_dir.startswith("/")
        path = ""
        for p in parts:
            path = f"{path}/{p}" if path else (f"/{p}" if absolute else p)
            try:
                self._sftp.stat(path)
            except IOError:
                try:
                    self._sftp.mkdir(path)
                    logger.info(f"SFTP: mkdir {path}")
                except Exception as ee:
                    if isinstance(ee, IOError) and getattr(ee, "errno", None) == errno.EACCES:
                        raise
                    logger.warning(f"SFTP: mkdir failed for {path}: {ee}")

    def upload_to_auto_dir(self, local_path: str):
        remote_dir = self.get_auto_remote_dir()
        fname = os.path.basename(local_path)
        target = (remote_dir.rstrip("/") + "/" + fname)
        # ensure dir
        tdir = os.path.dirname(target)
        if tdir and tdir not in (".", "/"):
            self.makedirs(tdir)
        logger.info(f"SFTP: uploading {local_path} -> {target}")
        self._sftp.put(local_path, target)
        logger.info("SFTP: upload OK")
