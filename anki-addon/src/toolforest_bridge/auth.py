"""Device-flow sign-in client (stdlib only).

RFC 8628-style: request a code, show the user the user_code + verification URL,
poll until they approve it in the Toolforest portal, then store the returned
bridge token in the add-on config.

Runs entirely on a worker thread — no Anki/Qt imports here.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

from . import protocol


class DeviceFlowError(Exception):
    pass


def _post(
    api_base: str,
    path: str,
    body: dict,
    timeout: float = 15.0,
    headers: dict | None = None,
) -> dict:
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(
        f"{api_base}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            raise DeviceFlowError(f"HTTP {exc.code} from {path}") from exc
    except urllib.error.URLError as exc:
        raise DeviceFlowError(f"Could not reach {api_base}: {exc.reason}") from exc


def start_device_flow(api_base: str, device_name: str) -> dict:
    """Returns {device_code, user_code, verification_uri, expires_in, interval}."""
    result = _post(api_base, "/device/code", {"device_name": device_name})
    if "device_code" not in result:
        raise DeviceFlowError(result.get("error", "device code request failed"))
    return result


def revoke_self(api_base: str, token: str) -> dict:
    """Revoke this add-on's current bridge token."""
    result = _post(
        api_base,
        "/device/revoke-self",
        {},
        timeout=10.0,
        headers={"Authorization": f"Bearer {token}"},
    )
    if result.get("revoked") is not True:
        raise DeviceFlowError(result.get("error", "revoke request failed"))
    return result


def poll_for_token(
    api_base: str,
    device_code: str,
    interval: int,
    expires_in: int,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> dict:
    """Poll /device/token until approved. Returns {access_token, device_id}.

    Raises DeviceFlowError on denial/expiry/cancel.
    """
    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        if should_cancel and should_cancel():
            raise DeviceFlowError("cancelled")
        result = _post(api_base, "/device/token", {"device_code": device_code})
        error = result.get("error")
        if not error and result.get("access_token"):
            return result
        if error == "authorization_pending":
            time.sleep(interval)
            continue
        raise DeviceFlowError(error or "token request failed")
    raise DeviceFlowError("expired_token")


def api_base_from_ws(ws_endpoint: str) -> str:
    """Derive the HTTP API base from the WS endpoint for the same environment.

    wss://bridge.toolforest.io        -> https://bridge-api.toolforest.io
    wss://bridge-dev.toolforest.io    -> https://bridge-api-dev.toolforest.io
    """
    host = ws_endpoint.replace("wss://", "").replace("ws://", "").rstrip("/")
    if host.startswith("bridge-") and "." in host:
        sub, rest = host.split(".", 1)
        env = sub[len("bridge-") :]
        return f"https://bridge-api-{env}.{rest}"
    if host.startswith("bridge."):
        return f"https://bridge-api.{host[len('bridge.') :]}"
    # Fallback: assume a default prod-style mapping
    return protocol.DEFAULT_API_URL
