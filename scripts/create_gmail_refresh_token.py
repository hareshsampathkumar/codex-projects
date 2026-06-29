import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
]


def main():
    client_secret_path = Path("client_secret.json")
    if not client_secret_path.exists():
        raise SystemExit(
            "Place your Google OAuth desktop client JSON at client_secret.json, then run this script again."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    print("\nAdd these values to GitHub Actions secrets:\n")
    with client_secret_path.open() as f:
        client_info = json.load(f).get("installed") or json.load(f).get("web")

    print(f"GMAIL_CLIENT_ID={client_info['client_id']}")
    print(f"GMAIL_CLIENT_SECRET={client_info['client_secret']}")
    print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")


if __name__ == "__main__":
    main()
