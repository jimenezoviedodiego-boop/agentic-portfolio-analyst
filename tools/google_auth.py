from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from tools.portfolio_lib import repo_root

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]


def credentials_path() -> Path:
    return repo_root() / "credentials.json"


def token_path() -> Path:
    return repo_root() / "token.json"


def get_credentials() -> Credentials:
    creds = None
    if token_path().exists():
        creds = Credentials.from_authorized_user_file(str(token_path()), SCOPES)

    if not creds or not creds.valid:
        refreshed = False
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                refreshed = True
            except RefreshError:
                # Revoked/expired refresh token: fall back to a fresh browser login
                pass
        if not refreshed:
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path()), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path().write_text(creds.to_json(), encoding="utf-8")

    return creds


def main():
    creds = get_credentials()
    print("Google auth OK. Token valid:", creds.valid)


if __name__ == "__main__":
    main()
