# Toolforest Bridge for Anki

An [Anki](https://apps.ankiweb.net/) add-on that connects your local Anki collection to [Toolforest](https://toolforest.io), so AI assistants can read and create flashcards through the Toolforest MCP platform — without exposing anything on your network.

## How it works

```
Anki collection  ←  Toolforest Bridge add-on  →  wss://bridge.toolforest.io
  local profile          native executor              Toolforest gateway
```

The add-on holds a single **outbound** WebSocket connection to the Toolforest bridge gateway. When a Toolforest tool call needs your Anki data, the gateway relays the request over that connection and the add-on executes it inside Anki through Anki's local Python APIs. Nothing on your machine listens for inbound connections, and your Anki data is only reachable while Anki is open.

## Install

1. Install **Toolforest Bridge** from [AnkiWeb](https://ankiweb.net/shared/info/1897413075): in Anki, open Tools → Add-ons → Get Add-ons… and enter code `1897413075`. Manual fallback: download the `.ankiaddon` file from the [latest GitHub release](../../releases/latest) and use Tools → Add-ons → Install from file…
2. Restart Anki, then Tools → Toolforest Bridge… → **Sign in**. You'll get a short code to confirm at toolforest.io/activate.

The status entry in the Tools menu shows Connected / Signed out / reconnecting states, and the status dialog reports that the native Anki executor is active.

## Privacy & security

- The add-on only ever dials **out** (WSS to the Toolforest gateway); it never listens on your network.
- Tool requests run inside the current Anki profile through the add-on; the server cannot redirect the bridge to arbitrary local services.
- Sign-in uses an OAuth device flow; the add-on stores a revocable bridge token, never your Toolforest password. Revoke any device at any time from your Toolforest account settings.

## Development

```bash
anki-addon/scripts/link.sh      # symlink the add-on into your local Anki addons21/ dir
anki-addon/scripts/package.sh   # build dist/toolforest_bridge.ankiaddon
python -m pytest anki-addon/tests
```

Set `endpoint_override` in the add-on config to point at a dev gateway. This changes the gateway URL only; local execution always happens inside the running Anki profile.

## Third-party notices

The packaged add-on vendors [websocket-client](https://github.com/websocket-client/websocket-client) (Apache License 2.0) under `anki-addon/src/toolforest_bridge/vendor/websocket/`; its license is included alongside the vendored code. This repository's own code is MIT-licensed (see [LICENSE](LICENSE)).
