# SigmaDesktop/modules/drive_handler.py
"""
Drive handler for SigmaDesktop (Sigma S1)
- Authenticates with a Service Account JSON (sigma-service-account.json at project root by default)
- Lists files in a Drive folder
- Downloads files (regular files + exports Google-native files when needed)
- Move files into an Archive folder in Drive (instead of deleting) after successful upload

Place this file: SigmaDesktop/modules/drive_handler.py
Service account JSON: SigmaDesktop/sigma-service-account.json
"""

import os
import io
import time
import logging
from typing import List, Dict, Optional, Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError

# ----- CONFIG -----
DEFAULT_SCOPES = ["https://www.googleapis.com/auth/drive"]
# service account file assumed at project root (one level up from modules/)
DEFAULT_SA_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "sigma-service-account.json")
)
# download chunk size
DEFAULT_CHUNK_SIZE = 32768

# default archive folder name in Drive root (will be created if missing)
DEFAULT_ARCHIVE_FOLDER_NAME = "Sigma_Archive"

# basic logger (you can inject your own logger object into functions)
logger = logging.getLogger("drive_handler")
if not logger.handlers:
    # basic console handler if no external logger is wired
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(ch)
    logger.setLevel(logging.INFO)


# ----- UTIL -----
def _ensure_dir(path: str):
    if not path:
        return
    os.makedirs(path, exist_ok=True)


def _retry(func, retries=3, base_sleep=1.0, logger=logger, *args, **kwargs):
    """Simple retry helper for network calls (exponential backoff)."""
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            return func(*args, **kwargs)
        except HttpError as e:
            last_exc = e
            logger.warning(f"HttpError on attempt {attempt}/{retries}: {e}")
            # if last attempt, re-raise
            if attempt == retries:
                raise
            sleep = base_sleep * (2 ** (attempt - 1))
            time.sleep(sleep)
        except Exception as e:
            last_exc = e
            logger.warning(f"Error on attempt {attempt}/{retries}: {e}")
            if attempt == retries:
                raise
            time.sleep(base_sleep * (2 ** (attempt - 1)))
    raise last_exc


# ----- AUTH -----
def get_drive_service(
    service_account_file: Optional[str] = None,
    scopes: Optional[List[str]] = None,
    delegated_user: Optional[str] = None,
) -> Any:
    """
    Authenticate using a service account JSON and return a Google Drive service object.
    - service_account_file: path to JSON (default: project root sigma-service-account.json)
    - scopes: list of scopes (default: full drive)
    - delegated_user: email to impersonate (optional, requires domain-wide delegation)
    """
    sa = service_account_file or DEFAULT_SA_PATH
    sc = scopes or DEFAULT_SCOPES

    if not os.path.exists(sa):
        raise FileNotFoundError(
            f"Service account file not found: {sa}\n"
            "Make sure sigma-service-account.json is placed at project root and its path is correct."
        )

    creds = service_account.Credentials.from_service_account_file(sa, scopes=sc)
    if delegated_user:
        creds = creds.with_subject(delegated_user)

    # use cache_discovery=False to avoid auto-downloading discovery doc in some envs
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return service


# ----- LIST FILES -----
def list_files_in_folder(
    folder_id: str,
    service,
    page_size: int = 100,
    extra_query: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    List files in a folder (non-trashed).
    - extra_query: additional Drive API query fragment (e.g., "mimeType='text/csv'")
    """
    q = f"'{folder_id}' in parents and trashed = false"
    if extra_query:
        q += f" and ({extra_query})"

    files: List[Dict[str, Any]] = []
    page_token = None
    while True:
        def _call():
            return service.files().list(
                q=q,
                pageSize=page_size,
                fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, parents)",
                pageToken=page_token,
            ).execute()

        resp = _retry(_call)
        items = resp.get("files", [])
        files.extend(items)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    logger.info(f"Found {len(files)} file(s) in folder {folder_id}")
    return files


# ----- DOWNLOAD -----
def download_file_to_path(
    file_meta: Dict[str, Any],
    dest_path: str,
    service,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> str:
    """
    Download a single file (or export Google-native) to dest_path.
    Returns dest_path on success.
    """
    file_id = file_meta.get("id")
    name = file_meta.get("name")
    mime = file_meta.get("mimeType", "")

    _ensure_dir(os.path.dirname(dest_path))
    logger.info(f"Downloading '{name}' (id={file_id}, mime={mime}) -> {dest_path}")

    def _do_download():
        # Google-native files need export_media
        if mime.startswith("application/vnd.google-apps."):
            # handle a few common types for export
            if mime == "application/vnd.google-apps.spreadsheet":
                export_mime = "text/csv"
            elif mime == "application/vnd.google-apps.document":
                export_mime = "application/pdf"
            elif mime == "application/vnd.google-apps.presentation":
                export_mime = "application/pdf"
            else:
                # fallback to PDF for unknown google-native types
                export_mime = "application/pdf"

            request = service.files().export_media(fileId=file_id, mimeType=export_mime)
        else:
            request = service.files().get_media(fileId=file_id)

        fh = io.FileIO(dest_path, mode="wb")
        downloader = MediaIoBaseDownload(fh, request, chunksize=chunk_size)

        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                logger.debug(f"Download {name}: {int(status.progress() * 100)}%")
        fh.close()

    _retry(_do_download)
    logger.info(f"Downloaded '{name}' -> {dest_path}")
    return dest_path


# ----- ARCHIVE / MOVE IN DRIVE -----
def _find_folder_in_root(folder_name: str, service) -> Optional[str]:
    """Return folder id if a folder with folder_name exists in root (not trashed)."""
    q = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and 'root' in parents and trashed = false"
    def _call():
        return service.files().list(q=q, fields="files(id, name)", pageSize=10).execute()
    resp = _retry(_call)
    items = resp.get("files", [])
    if not items:
        return None
    return items[0].get("id")


def _create_folder_in_root(folder_name: str, service) -> str:
    """Create a folder in Drive root and return its id."""
    body = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder", "parents": ["root"]}
    def _call():
        return service.files().create(body=body, fields="id,name").execute()
    resp = _retry(_call)
    fid = resp.get("id")
    logger.info(f"Created Drive folder '{folder_name}' (id={fid}) in root")
    return fid


def get_or_create_archive_folder(service, folder_name: Optional[str] = None) -> str:
    """Get the archive folder id (create if missing)."""
    name = folder_name or DEFAULT_ARCHIVE_FOLDER_NAME
    fid = _find_folder_in_root(name, service)
    if fid:
        logger.debug(f"Found existing archive folder '{name}' (id={fid})")
        return fid
    return _create_folder_in_root(name, service)


def move_file_to_archive(file_id: str, service, archive_folder_name: Optional[str] = None) -> bool:
    """
    Move a file into the archive folder in Drive root.
    This uses Files.get to read current parents and Files.update to addParents/removeParents.
    Returns True on success.
    """
    try:
        archive_id = get_or_create_archive_folder(service, archive_folder_name)
        # get current parents
        def _get_parents():
            return service.files().get(fileId=file_id, fields="id, name, parents").execute()
        meta = _retry(_get_parents)
        parents = meta.get("parents", [])
        # If already in archive, nothing to do
        if archive_id in parents:
            logger.info(f"File {file_id} already in archive folder {archive_id}")
            return True

        remove_parents = ",".join(parents) if parents else None
        def _update():
            kwargs = {"fileId": file_id, "addParents": archive_id, "fields": "id, parents"}
            if remove_parents:
                kwargs["removeParents"] = remove_parents
            return service.files().update(**kwargs).execute()

        _retry(_update)
        logger.info(f"Moved file id={file_id} to archive folder id={archive_id}")
        return True
    except Exception as e:
        logger.exception(f"Failed to move file {file_id} to archive: {e}")
        return False


# ----- DELETE FROM DRIVE (kept for compatibility, but watcher now uses move) -----
def delete_file(file_id: str, service) -> None:
    """Delete a file from Drive (trashed/permanently deleted depending on permissions)."""
    def _do_delete():
        return service.files().delete(fileId=file_id).execute()

    _retry(_do_delete)
    logger.info(f"Deleted file id={file_id} from Drive")


# ----- HIGH-LEVEL: DOWNLOAD ALL NEW FILES -----
def download_all_from_folder(
    folder_id: str,
    dest_dir: str,
    service,
    delete_after_download: bool = False,
    allowed_name_prefix: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    List files in folder_id and download each file into dest_dir.
    Returns a list of result dicts: {id,name,path,status,message}
    - allowed_name_prefix: if set, only files with name starting with prefix will be downloaded
    - delete_after_download: if True, will delete the file from Drive after download (legacy)
    """
    results = []
    files = list_files_in_folder(folder_id, service)

    for f in files:
        fid = f.get("id")
        fname = f.get("name")
        if allowed_name_prefix and not fname.startswith(allowed_name_prefix):
            logger.debug(f"Skipping '{fname}' since it does not match prefix '{allowed_name_prefix}'")
            continue
        safe_name = fname.replace("/", "_")  # simple safety
        dest_path = os.path.join(dest_dir, safe_name)
        try:
            download_file_to_path(f, dest_path, service)
            if delete_after_download:
                delete_file(fid, service)
            results.append({"id": fid, "name": fname, "path": dest_path, "status": "OK", "message": ""})
        except Exception as e:
            logger.exception(f"Failed to handle file {fname} ({fid}): {e}")
            results.append({"id": fid, "name": fname, "path": dest_path, "status": "ERROR", "message": str(e)})
    return results


# ----- CLI / quick test -----
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Drive handler test tool (SigmaDesktop)")
    ap.add_argument("--service-account", default=None, help="Path to service account JSON (default: project root sigma-service-account.json)")
    ap.add_argument("--folder-id", required=True, help="Drive folder ID to read from")
    ap.add_argument("--dest", default=os.path.join(os.path.expanduser("~"), "Desktop", "temp_files"), help="Local destination folder")
    ap.add_argument("--delete", action="store_true", help="Delete files from Drive after successful download")
    ap.add_argument("--prefix", default=None, help="Only download files with this name prefix (optional)")
    ap.add_argument("--archive-name", default=None, help="Archive folder name to use (optional)")

    args = ap.parse_args()
    sa_file = args.service_account or DEFAULT_SA_PATH
    try:
        svc = get_drive_service(service_account_file=sa_file)
        print("Authenticated OK.")
        print("Listing & downloading...")
        out = download_all_from_folder(
            folder_id=args.folder_id,
            dest_dir=args.dest,
            service=svc,
            delete_after_download=args.delete,
            allowed_name_prefix=args.prefix,
        )
        print("Results:")
        for r in out:
            print(r)
    except Exception as e:
        logger.exception("Drive handler test failed: %s", e)
        raise
