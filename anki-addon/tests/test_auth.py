import sys
from pathlib import Path

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
