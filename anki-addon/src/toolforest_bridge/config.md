# Toolforest Bridge configuration

Use Tools → Toolforest Bridge… to sign in and manage the connection. You normally
don't need to edit this config by hand.

- `bridge_token`: The device token issued when you sign in. Set automatically by
  the sign-in flow. During early testing a token may be provisioned for you to
  paste here directly.
- `endpoint_override`: Alternative bridge gateway URL (`wss://…`). For development
  against a non-production Toolforest environment only. This changes the gateway
  the add-on connects **to**; the local forwarding target is always AnkiConnect on
  `127.0.0.1:8765` and cannot be changed.
- `ankiconnect_url`: Local AnkiConnect endpoint. Default `http://127.0.0.1:8765`.
- `ankiconnect_key`: If you set an `apiKey` in AnkiConnect's own config, put the
  same value here so the bridge can authenticate to it. Leave `null` otherwise.
