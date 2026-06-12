# Toolforest Bridge for Anki

An [Anki](https://apps.ankiweb.net/) add-on that connects your local Anki collection to [Toolforest](https://toolforest.io), so AI assistants can read and create flashcards through the Toolforest MCP platform — without exposing anything on your network.

## How it works

```
AnkiConnect (localhost:8765)  ←  Toolforest Bridge add-on  →  wss://bridge.toolforest.io
        stock, unmodified            this repo, outbound-only        Toolforest gateway
```

The add-on holds a single **outbound** WebSocket connection to the Toolforest bridge gateway. When a Toolforest tool call needs your Anki data, the gateway relays the request over that connection and the add-on forwards it to [AnkiConnect](https://ankiweb.net/shared/info/2055492159) on `127.0.0.1:8765` — and nowhere else; the local target is hard-coded. Nothing on your machine listens for inbound connections, and your Anki data is only reachable while Anki is open.

## Install

1. Install **AnkiConnect**: in Anki, Tools → Add-ons → Get Add-ons… → code `2055492159`.
2. Install **Toolforest Bridge**: code `TBD` (AnkiWeb listing pending), or download the `.ankiaddon` file from the [latest GitHub release](../../releases/latest) and use Tools → Add-ons → Install from file…
3. Restart Anki, then Tools → Toolforest Bridge… → **Sign in**. You'll get a short code to confirm at toolforest.io/activate.

The status entry in the Tools menu shows Connected / Signed out / AnkiConnect missing.

## Privacy & security

- The add-on only ever dials **out** (WSS to the Toolforest gateway); it never listens on your network.
- It forwards requests exclusively to AnkiConnect on `127.0.0.1:8765`. The server cannot redirect it elsewhere.
- Sign-in uses an OAuth device flow; the add-on stores a revocable bridge token, never your Toolforest password. Revoke any device at any time from your Toolforest account settings.

## Development

```bash
anki-addon/scripts/link.sh      # symlink the add-on into your local Anki addons21/ dir
anki-addon/scripts/package.sh   # build dist/toolforest_bridge.ankiaddon
python -m pytest anki-addon/tests
```

Set `endpoint_override` in the add-on config to point at a dev gateway. This changes the gateway URL only — the local AnkiConnect target is not configurable.

## Third-party notices

The packaged add-on vendors [websocket-client](https://github.com/websocket-client/websocket-client) (Apache License 2.0) under `anki-addon/src/toolforest_bridge/vendor/websocket/`; its license is included alongside the vendored code. This repository's own code is MIT-licensed (see [LICENSE](LICENSE)).

This project speaks plain HTTP to AnkiConnect and does not modify, link, or redistribute it.
