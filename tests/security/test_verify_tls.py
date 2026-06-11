import inspect

from app.integrations.google.drive_client import DriveClient
from app.integrations.slack.slack_client import SlackClient
from app.shared.http_client import HttpClient


def test_http_client_enables_tls_verification():
    source = inspect.getsource(HttpClient.init)
    assert "verify=True" in source or "verify = True" in source


def test_drive_client_enables_tls_verification():
    source = inspect.getsource(DriveClient.init)
    assert "verify=True" in source or "verify = True" in source


def test_slack_client_enables_tls_verification():
    source = inspect.getsource(SlackClient.init)
    assert "verify=True" in source or "verify = True" in source
