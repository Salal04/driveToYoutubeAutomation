"""
drive_sync.py

Mirrors a Google Drive folder tree to local disk using a SERVICE ACCOUNT.
(Service accounts work fine for Drive -- unlike YouTube uploads.)

Expected Drive structure (matches your local layout):

  <DRIVE_ROOT_FOLDER_ID>/           output/
    video_name1/                     video_name1/
      chunk_videos/          -->        chunk_videos/
        video_name1-chunk1.mp4            video_name1-chunk1.mp4
        video_name1-chunk2.mp4            video_name1-chunk2.mp4
    video_name2/
      chunk_videos/
        ...

IMPORTANT: share the Drive folder with the service account's client_email
(found inside the service account JSON key) or it won't see anything.
"""

import io
import logging
import os

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account

logger = logging.getLogger("drive_sync")

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER_MIME = "application/vnd.google-apps.folder"


def get_drive_service(service_account_path: str):
    creds = service_account.Credentials.from_service_account_file(
        service_account_path, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _list_children(service, folder_id: str):
    items = []
    page_token = None
    query = f"'{folder_id}' in parents and trashed = false"
    while True:
        resp = (
            service.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType, size, md5Checksum)",
                pageToken=page_token,
            )
            .execute()
        )
        items.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return items


def _download_file(service, file_id: str, dest_path: str):
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    request = service.files().get_media(fileId=file_id)
    with io.FileIO(dest_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=1024 * 1024 * 10)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                logger.info("  downloading %s: %d%%", os.path.basename(dest_path), int(status.progress() * 100))


def sync_folder(service, drive_folder_id: str, local_path: str, depth: int = 0):
    """Recursively mirror drive_folder_id -> local_path. Skips files that
    already exist locally with the same size (cheap re-run safety)."""
    os.makedirs(local_path, exist_ok=True)
    children = _list_children(service, drive_folder_id)

    if depth == 0 and not children:
        logger.warning(
            "Drive folder id '%s' returned ZERO items. This usually means: "
            "(1) the folder ID is wrong/stale, (2) the service account no "
            "longer has Viewer access to it, or (3) the folder is genuinely "
            "empty. Double-check the DRIVE_ROOT_FOLDER_ID secret and that "
            "the folder is still shared with the service account's "
            "client_email.",
            drive_folder_id,
        )

    for item in children:
        name = item["name"]
        target = os.path.join(local_path, name)
        if item["mimeType"] == FOLDER_MIME:
            sync_folder(service, item["id"], target, depth=depth + 1)
        else:
            remote_size = int(item.get("size", 0) or 0)
            if os.path.exists(target) and remote_size and os.path.getsize(target) == remote_size:
                logger.debug("Skipping already-downloaded file: %s", target)
                continue
            logger.info("Downloading %s -> %s", name, target)
            _download_file(service, item["id"], target)


def sync_from_drive(service_account_path: str, drive_root_folder_id: str, local_output_dir: str):
    service = get_drive_service(service_account_path)
    sync_folder(service, drive_root_folder_id, local_output_dir)
