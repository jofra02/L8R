# Gateway Secrets

> Encrypt device tokens and rotate the inventory master key.

Device API tokens are stored as `ENC(<fernet>)` in the gateway's inventory YAML and decrypted in memory with `INVENTORY_MASTER_KEY`. Live inventory files and `.env` are **gitignored**.

Tokens submitted through the inventory admin API (frontend "MCP managed device" flow) are encrypted **server-side by the gateway** before hitting disk (`devices/managed.yaml`); the app forwards them write-only and never stores them — Postgres holds no appliance credentials. If `INVENTORY_MASTER_KEY` is unset, admin writes carrying a token fail with 503.

## Risk assessment (context for rotation)

The master key was **never committed to git** (verified across the full history of both repos) and both repos are private. What *does* exist in the archived `fortinet_ai_suite` history are the **encrypted** `ENC(...)` token ciphertexts plus identifiable customer data. Without the key the ciphertexts are unusable. Therefore: **rotation is recommended hygiene, not urgent incident response.** Regenerating the FortiGate API tokens themselves is the stronger, optional follow-up.

## Generate a key / encrypt a token

```bash
cd mcp_gateway
uv run python scripts/encrypt_secret.py --generate            # new Fernet master key
uv run python scripts/encrypt_secret.py "<device-api-token>"  # → ENC(...) to paste into YAML
uv run python scripts/encrypt_secret.py --batch in.csv --output out.csv   # bulk (token column)
```

## Rotate the master key

**Purpose**: re-encrypt every `ENC(...)` value under `mcp_gateway/inventory/` with a new key.

1. Generate the new key (`--generate` above). Keep the old one at hand.
2. Dry run:
   ```bash
   uv run python scripts/rotate_master_key.py --old-key "<OLD>" --new-key "<NEW>" --dry-run
   ```
3. Apply (same command without `--dry-run`). Re-encryption is textual — YAML comments/formatting are preserved.
4. Update `INVENTORY_MASTER_KEY` in **both** places:
   - `mcp_gateway/.env` (host runs)
   - the repo-root `.env` (compose passes it to the `mcp-gateway` service)
5. Restart the gateway: `docker compose up -d mcp-gateway`.

**Verification**: startup log shows `Loaded N 'fortios' devices` (decryption OK), then one live read-only tool call per tenant (e.g. `fgt_monitor_sys_get_status` with `device: <id>`). A decryption failure logs `Decryption failed. Check your INVENTORY_MASTER_KEY.`

**Rollback**: run `rotate_master_key.py` again with the keys swapped, restore the old key in the `.env` files, restart.

## Optional: regenerate the appliance tokens

For each FortiGate: FortiOS → System → Administrators → the REST API admin → regenerate token; then `encrypt_secret.py "<new-token>"` and replace the `ENC(...)` value in the device YAML; restart the gateway.

## Gotchas

- Old backups of the inventory YAML remain encrypted with the **old** key — note the rotation date in your backup records.
- The two `.env` files (gateway + repo root) drift easily; if compose works but host runs fail (or vice versa), compare them.
