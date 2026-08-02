"""
youtube_uploader.py

Uploads a video file to YouTube using OAuth2 (refresh token), NOT an API
key and NOT a service account -- YouTube uploads require a real user's
consent via OAuth2. Run get_youtube_refresh_token.py once locally to obtain
the refresh token, then store client_id / client_secret / refresh_token as
GitHub Actions secrets.
"""

import http.client
import logging
import random
import time

import httplib2
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger("youtube_uploader")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# Errors worth retrying on (transient)
RETRIABLE_STATUS_CODES = (500, 502, 503, 504)
RETRIABLE_EXCEPTIONS = (
    httplib2.HttpLib2Error,
    IOError,
    http.client.NotConnected,
    http.client.IncompleteRead,
    http.client.ImproperConnectionState,
    http.client.CannotSendRequest,
    http.client.CannotSendHeader,
    http.client.ResponseNotReady,
    http.client.BadStatusLine,
)

MAX_RETRIES = 8


def get_youtube_service(client_id: str, client_secret: str, refresh_token: str):
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload_video(
    youtube,
    file_path: str,
    title: str,
    description: str = "",
    tags=None,
    category_id: str = "22",
    privacy_status: str = "public",
) -> str:
    """Resumable upload. Returns the uploaded video's YouTube ID."""
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags or [],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,  # 'public' | 'unlisted' | 'private'
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(file_path, chunksize=1024 * 1024 * 8, resumable=True, mimetype="video/mp4")

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    retry = 0
    while response is None:
        try:
            logger.info("Uploading chunk of %s ...", file_path)
            status, response = request.next_chunk()
            if status:
                logger.info("  progress: %d%%", int(status.progress() * 100))
        except HttpError as e:
            if e.resp.status in RETRIABLE_STATUS_CODES:
                retry += 1
                if retry > MAX_RETRIES:
                    raise
                sleep_seconds = min(64, 2 ** retry) + random.random()
                logger.warning("Retriable HTTP error %s, retrying in %.1fs", e.resp.status, sleep_seconds)
                time.sleep(sleep_seconds)
            else:
                raise
        except RETRIABLE_EXCEPTIONS:
            retry += 1
            if retry > MAX_RETRIES:
                raise
            sleep_seconds = min(64, 2 ** retry) + random.random()
            logger.warning("Retriable error, retrying in %.1fs", sleep_seconds)
            time.sleep(sleep_seconds)

    return response["id"]
