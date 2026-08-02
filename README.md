# InstaUploaderPipeline

Pulls video chunks from Google Drive and uploads them to YouTube (as
Shorts/reels) in strict sequential order, keeping a permanent record so
nothing is ever uploaded twice or out of order. Runs automatically every
3 hours via GitHub Actions.

## Expected folder structure (local and on Drive, must match)

```
output/
  video_name1/
    chunk_videos/
      video_name1-chunk1.mp4
      video_name1-chunk2.mp4
      video_name1-chunk3.mp4
  video_name2/
    chunk_videos/
      video_name2-chunk1.mp4
      ...
```

Drop new `video_nameN` folders into Drive any time — the next scheduled
run (within 3 hours) will pick them up automatically.

## Why not just an API key?

The YouTube Data API **rejects video uploads made with a plain API key**,
and it also does **not support service accounts** for uploading to a
personal channel. Uploading requires OAuth2 consent from the channel
owner once, after which a **refresh token** lets automation upload
indefinitely without human interaction. Google Drive, by contrast, works
great with a service account (no human needed).

## One-time setup

### 1. Google Drive (service account)
1. In [Google Cloud Console](https://console.cloud.google.com/), create/select
   a project and enable the **Google Drive API**.
2. Create a **Service Account**, then create a JSON key for it.
3. Share your Drive `output` root folder with the service account's
   `client_email` (found in the JSON key) as a **Viewer**.
4. Copy the folder's ID from its Drive URL (`.../folders/<THIS_PART>`).

### 2. YouTube (OAuth2 refresh token)
1. In the same or another Cloud project, enable **YouTube Data API v3**.
2. Under **OAuth consent screen**, add yourself as a test user (or publish it).
3. Create an **OAuth Client ID** of type **Desktop app**, download it as
   `client_secret.json`.
4. Locally (not in CI), run:
   ```
   pip install -r requirements.txt
   python get_youtube_refresh_token.py
   ```
   Log in with the YouTube channel you want to upload to. Copy the printed
   `client_id`, `client_secret`, and `refresh_token`.

### 3. GitHub repo secrets
Go to **Settings → Secrets and variables → Actions** and add:

| Secret | Value |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | full contents of the service account JSON key |
| `DRIVE_ROOT_FOLDER_ID` | the Drive folder ID from step 1.4 |
| `YOUTUBE_CLIENT_ID` | from step 2.4 |
| `YOUTUBE_CLIENT_SECRET` | from step 2.4 |
| `YOUTUBE_REFRESH_TOKEN` | from step 2.4 |

Optional repo **variable**: `YOUTUBE_PRIVACY_STATUS` (`public` / `unlisted` /
`private`, defaults to `public`).

### 4. Enable the workflow
Push this repo to GitHub with `.github/workflows/upload.yml` included. It
runs automatically every 3 hours, and you can also trigger it manually from
the **Actions** tab (`Run workflow`).

## How the ledger works

`records/upload_record.json` tracks every chunk ever seen:

```json
{
  "Yaddon-ki-tajir": {
    "chunks": {
      "Yaddon-ki-tajir-chunk1": {"status": "uploaded", "youtube_id": "abc123", "uploaded_at": "..."},
      "Yaddon-ki-tajir-chunk2": {"status": "pending"}
    }
  }
}
```

- A chunk only uploads once its earlier siblings show `"status": "uploaded"`.
- The Action commits this file back to the repo after every run, so state
  is never lost between scheduled runs.

## Local test run

```
pip install -r requirements.txt
export DRIVE_ROOT_FOLDER_ID=...          # optional, omit to use local ./output as-is
export GOOGLE_SERVICE_ACCOUNT_FILE=service_account.json
export YOUTUBE_CLIENT_ID=...
export YOUTUBE_CLIENT_SECRET=...
export YOUTUBE_REFRESH_TOKEN=...
python main.py
```

## Quota note

Each YouTube upload costs 1600 of your 10,000 default daily quota units
(~6 uploads/day). If you have more chunks than that, request a quota
increase in Google Cloud Console under the YouTube Data API v3 page.
