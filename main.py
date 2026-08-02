"""
main.py

InstaUploaderPipeline entrypoint.

Expected local structure (mirrored from Drive by drive_sync.py):

  output/
    video_name1/
      chunk_videos/
        video_name1-chunk1.mp4
        video_name1-chunk2.mp4
        video_name1-chunk3.mp4
    video_name2/
      chunk_videos/
        ...

Rules enforced:
  - A chunk is only uploaded if all earlier chunks of the same video are
    already marked "uploaded" in the ledger (strict sequential order).
  - Every video/chunk is uploaded at most once, ever (tracked in the
    JSON ledger at records/upload_record.json).
  - New videos/chunks dropped into Drive at any time are picked up on the
    next run automatically -- nothing needs to be told about them.
"""

import logging
import os
import sys

from drive_sync import sync_from_drive
from record_manager import (
    DEFAULT_RECORD_PATH,
    chunk_sort_key,
    get_chunk_status,
    load_record,
    mark_failed,
    mark_uploaded,
    mark_uploading,
    save_record,
)
from youtube_uploader import get_youtube_service, upload_video

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

OUTPUT_DIR = os.environ.get("LOCAL_OUTPUT_DIR", "output")
VIDEO_EXTENSIONS = (".mp4", ".mov", ".m4v")
CHUNK_FOLDER_NAMES = ("chunk_videos", "chunk videos")


def discover_videos(output_dir: str):
    """Yields (video_name, [chunk_file_paths_in_order]) for every
    chunk_videos folder found ANYWHERE under output_dir, at any nesting
    depth. This makes the pipeline tolerant of extra wrapper folders
    (e.g. Drive shared at a parent level, extra "output/output" nesting)
    and unrelated sibling files/folders (assets/, sources/, *.json, etc.)
    -- it only cares about folders literally named 'chunk_videos'.

    video_name is taken from the immediate parent folder of chunk_videos
    (e.g. '.../yaadon-ki-tajir_v3/chunk_videos/...' -> 'yaadon-ki-tajir_v3').
    If two different chunk_videos folders share the same parent folder
    name, the full relative path is used instead to avoid collisions in
    the ledger.
    """
    if not os.path.isdir(output_dir):
        logger.warning("Output dir '%s' does not exist yet.", output_dir)
        return

    found = []  # (video_name, chunk_folder_path)
    seen_names = {}

    for root, dirs, _files in os.walk(output_dir):
        base = os.path.basename(root)
        if base in CHUNK_FOLDER_NAMES:
            parent_name = os.path.basename(os.path.dirname(root))
            video_name = parent_name or base
            seen_names.setdefault(video_name, []).append(root)
            # Don't descend into chunk_videos looking for nested chunk_videos
            dirs[:] = []

    for video_name, folders in seen_names.items():
        for chunk_folder in sorted(folders):
            # Disambiguate if the same parent-folder name appears more than
            # once anywhere in the tree (rare, but safer than silently
            # merging their ledgers).
            key = video_name
            if len(folders) > 1:
                key = os.path.relpath(os.path.dirname(chunk_folder), output_dir)

            chunk_files = [
                f for f in os.listdir(chunk_folder)
                if f.lower().endswith(VIDEO_EXTENSIONS)
            ]
            chunk_files.sort(key=chunk_sort_key)

            if not chunk_files:
                logger.warning("chunk_videos folder '%s' has no video files, skipping.", chunk_folder)
                continue

            found.append((key, [os.path.join(chunk_folder, f) for f in chunk_files]))

    found.sort(key=lambda item: item[0])
    for video_name, chunk_paths in found:
        yield video_name, chunk_paths


def run_drive_sync():
    service_account_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
    drive_folder_id = os.environ.get("DRIVE_ROOT_FOLDER_ID", "").strip()

    if not drive_folder_id:
        logger.info("DRIVE_ROOT_FOLDER_ID not set, skipping Drive sync (using local '%s' as-is).", OUTPUT_DIR)
        return
    if not os.path.exists(service_account_path):
        logger.warning("Service account file '%s' not found, skipping Drive sync.", service_account_path)
        return

    logger.info("Syncing from Google Drive folder %s -> %s ...", drive_folder_id, OUTPUT_DIR)
    sync_from_drive(service_account_path, drive_folder_id, OUTPUT_DIR)
    logger.info("Drive sync complete.")


def run_uploads(record: dict):
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    privacy_status = os.environ.get("YOUTUBE_PRIVACY_STATUS", "public")

    if not all([client_id, client_secret, refresh_token]):
        logger.error("Missing YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET / YOUTUBE_REFRESH_TOKEN env vars.")
        sys.exit(1)

    youtube = get_youtube_service(client_id, client_secret, refresh_token)

    # How many chunks to upload in this single run. Defaults to 1 so that
    # every scheduled run (every 3 hours) uploads exactly one video/chunk,
    # instead of draining the whole backlog (and the daily quota) at once.
    max_uploads_per_run = int(os.environ.get("MAX_UPLOADS_PER_RUN", "1"))

    any_uploaded = False
    uploads_done_this_run = 0

    for video_name, chunk_paths in discover_videos(OUTPUT_DIR):
        if uploads_done_this_run >= max_uploads_per_run:
            break

        for chunk_path in chunk_paths:
            if uploads_done_this_run >= max_uploads_per_run:
                break

            chunk_name = os.path.splitext(os.path.basename(chunk_path))[0]
            status = get_chunk_status(record, video_name, chunk_name)

            if status == "uploaded":
                continue  # already done, never re-upload

            if status == "uploading":
                # A previous run crashed mid-upload. Safe to retry since
                # YouTube dedups partial resumable sessions server-side;
                # worst case is a fresh attempt.
                logger.warning("Chunk '%s' was left mid-upload, retrying.", chunk_name)

            # --- enforce strict sequential order ---
            # discover_videos already returns chunks pre-sorted, so we just
            # need to check every *earlier* chunk in this list is uploaded.
            earlier_chunks = [
                os.path.splitext(os.path.basename(p))[0]
                for p in chunk_paths
                if p != chunk_path and chunk_sort_key(os.path.basename(p)) < chunk_sort_key(os.path.basename(chunk_path))
            ]
            blocked = [c for c in earlier_chunks if get_chunk_status(record, video_name, c) != "uploaded"]
            if blocked:
                logger.info(
                    "Skipping '%s' — waiting on earlier chunk(s) %s to upload first.",
                    chunk_name, blocked,
                )
                break  # stop processing this video's remaining chunks this run

            logger.info("Uploading '%s' (video: %s) ...", chunk_name, video_name)
            mark_uploading(record, video_name, chunk_name)
            save_record(record, DEFAULT_RECORD_PATH)  # persist BEFORE upload starts

            try:
                youtube_id = upload_video(
                    youtube,
                    chunk_path,
                    title=f"{video_name} - {chunk_name} #Shorts",
                    description=f"{video_name}\n\n#Shorts",
                    privacy_status=privacy_status,
                )
                mark_uploaded(record, video_name, chunk_name, youtube_id)
                logger.info("Uploaded '%s' -> https://youtube.com/shorts/%s", chunk_name, youtube_id)
                any_uploaded = True
                uploads_done_this_run += 1
            except Exception as e:
                logger.exception("Failed to upload '%s'", chunk_name)
                mark_failed(record, video_name, chunk_name, str(e))
                save_record(record, DEFAULT_RECORD_PATH)
                # Don't upload later chunks of this video out of order after a failure
                break

            save_record(record, DEFAULT_RECORD_PATH)  # persist AFTER upload succeeds

    if not any_uploaded:
        logger.info("Nothing new to upload this run.")


def main():
    run_drive_sync()
    record = load_record(DEFAULT_RECORD_PATH)
    run_uploads(record)
    save_record(record, DEFAULT_RECORD_PATH)


if __name__ == "__main__":
    main()
