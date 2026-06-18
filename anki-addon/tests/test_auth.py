import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toolforest_bridge import auth  # noqa: E402


def test_api_base_from_prod_ws():
    assert auth.api_base_from_ws("wss://bridge.toolforest.io") == (
        "https://bridge-api.toolforest.io"
    )


def test_api_base_from_dev_ws():
    assert auth.api_base_from_ws("wss://bridge-dev.toolforest.io") == (
        "https://bridge-api-dev.toolforest.io"
    )


def test_api_base_strips_trailing_slash():
    assert auth.api_base_from_ws("wss://bridge-test.toolforest.io/") == (
        "https://bridge-api-test.toolforest.io"
    )


def test_revoke_self_posts_bridge_token():
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"revoked": true}'

    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["authorization"] = request.get_header("Authorization")
        seen["body"] = request.data
        seen["timeout"] = timeout
        return FakeResponse()

    with patch("urllib.request.urlopen", fake_urlopen):
        assert auth.revoke_self("https://bridge-api-dev.toolforest.io", "tok") == {
            "revoked": True
        }

    assert seen == {
        "url": "https://bridge-api-dev.toolforest.io/device/revoke-self",
        "method": "POST",
        "authorization": "Bearer tok",
        "body": b"{}",
        "timeout": 10.0,
    }
