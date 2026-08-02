"""
get_youtube_refresh_token.py

RUN THIS ONCE, LOCALLY (on your own laptop, not in GitHub Actions).
It opens a browser, asks you to log into the YouTube channel you want to
upload to, and prints a refresh_token. Save that refresh_token (plus your
client_id / client_secret) as GitHub Actions secrets:

  YOUTUBE_CLIENT_ID
  YOUTUBE_CLIENT_SECRET
  YOUTUBE_REFRESH_TOKEN

Prerequisite: in Google Cloud Console, create an OAuth 2.0 Client ID of
type "Desktop app", enable the "YouTube Data API v3", and download the
client secret JSON as client_secret.json in this folder.
"""

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def main():
    flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
    creds = flow.run_local_server(port=0)
    print("\n=== SAVE THESE AS GITHUB SECRETS ===")
    print("YOUTUBE_CLIENT_ID     =", creds.client_id)
    print("YOUTUBE_CLIENT_SECRET =", creds.client_secret)
    print("YOUTUBE_REFRESH_TOKEN =", creds.refresh_token)
    print("=====================================")

if __name__ == "__main__":
    main()
