from google.auth.exceptions import RefreshError

from tools import google_auth


class _DeadCreds:
    valid = False
    expired = True
    refresh_token = "revoked"

    def refresh(self, request):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")


class _FreshCreds:
    valid = True

    def to_json(self):
        return "{}"


def test_revoked_token_falls_back_to_browser_login(tmp_path, monkeypatch):
    token = tmp_path / "token.json"
    token.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(google_auth, "token_path", lambda: token)
    monkeypatch.setattr(google_auth.Credentials, "from_authorized_user_file", lambda *a, **k: _DeadCreds())

    class _Flow:
        def run_local_server(self, port):
            return _FreshCreds()

    monkeypatch.setattr(google_auth.InstalledAppFlow, "from_client_secrets_file", lambda *a, **k: _Flow())
    assert google_auth.get_credentials().valid
