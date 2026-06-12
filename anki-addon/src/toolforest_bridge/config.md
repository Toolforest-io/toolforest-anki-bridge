# Toolforest Bridge configuration

Use Tools → Toolforest Bridge… to sign in and manage the connection. You normally
don't need to edit this config by hand.

- `endpoint_override`: Alternative bridge gateway URL (`wss://…`). For development
  against a non-production Toolforest environment only. This changes the gateway the
  add-on connects **to**; the local forwarding target is always AnkiConnect on
  `127.0.0.1:8765` and cannot be changed.
- `ankiconnect_key`: If you have set an `apiKey` in AnkiConnect's own config, put the
  same value here so the bridge can authenticate to it. Leave `null` otherwise.
