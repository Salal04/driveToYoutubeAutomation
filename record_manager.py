"""
record_manager.py

Keeps a persistent JSON "ledger" of every video/chunk we've ever seen and
whether it has been uploaded to YouTube. This is what prevents:
  - re-uploading the same chunk twice
  - uploading chunk 2 before chunk 1 has finished uploading

The ledger is just a JSON file. In GitHub Actions we commit it back to the
repo after every run so state survives between runs (the runner itself is
thrown away after each job).
"""

import json
import os
import re
import tempfile
from datetime import datetime, timezone

DEFAULT_RECORD_PATH = os.environ.get("RECORD_PATH", "records/upload_record.json")


def load_record(path: str = DEFAULT_RECORD_PATH) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            # Corrupt/empty file -> start fresh rather than crash the pipeline
            return {}


def save_record(record: dict, path: str = DEFAULT_RECORD_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    # Atomic write so a crash mid-save never corrupts the ledger
    dir_ = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_video_entry(record: dict, video_name: str) -> dict:
    return record.setdefault(video_name, {"chunks": {}})


def get_chunk_status(record: dict, video_name: str, chunk_name: str) -> str:
    return (
        record.get(video_name, {})
        .get("chunks", {})
        .get(chunk_name, {})
        .get("status", "pending")
    )


def mark_uploading(record: dict, video_name: str, chunk_name: str) -> None:
    entry = get_video_entry(record, video_name)
    entry["chunks"][chunk_name] = {
        "status": "uploading",
        "started_at": now_iso(),
    }


def mark_uploaded(record: dict, video_name: str, chunk_name: str, youtube_id: str) -> None:
    entry = get_video_entry(record, video_name)
    entry["chunks"][chunk_name] = {
        "status": "uploaded",
        "youtube_id": youtube_id,
        "youtube_url": f"https://youtube.com/shorts/{youtube_id}",
        "uploaded_at": now_iso(),
    }


def mark_failed(record: dict, video_name: str, chunk_name: str, error: str) -> None:
    entry = get_video_entry(record, video_name)
    entry["chunks"][chunk_name] = {
        "status": "failed",
        "error": str(error)[:500],
        "failed_at": now_iso(),
    }


_NUM_RE = re.compile(r"(\d+)(?=\D*$)")


def chunk_sort_key(filename: str):
    """
    Sort 'video-chunk1', 'video-chunk2', ..., 'video-chunk10' in natural
    numeric order (not lexicographic, which would put chunk10 before chunk2).
    """
    match = _NUM_RE.search(os.path.splitext(filename)[0])
    number = int(match.group(1)) if match else 0
    return (number, filename)
