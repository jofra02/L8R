#!/usr/bin/env python
"""Rotate the INVENTORY_MASTER_KEY: re-encrypt every ENC(...) value in the
inventory YAML files with a new Fernet key.

Usage:
    # 1. Generate a new key first:
    uv run python scripts/encrypt_secret.py --generate

    # 2. Dry-run (shows which files/values would change):
    uv run python scripts/rotate_master_key.py --old-key <OLD> --new-key <NEW> --dry-run

    # 3. Apply:
    uv run python scripts/rotate_master_key.py --old-key <OLD> --new-key <NEW>

    # 4. Update INVENTORY_MASTER_KEY in .env (and compose env) to the new key.

Re-encryption is textual: only ENC(...) substrings are replaced, so YAML
formatting and comments are preserved.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gateway.inventory.secrets import SecretManager  # noqa: E402

INVENTORY_ROOT = Path(__file__).resolve().parents[1] / "inventory"
ENC_PATTERN = re.compile(r"ENC\([^)]+\)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Rotate the inventory master key")
    parser.add_argument("--old-key", required=True, help="Current Fernet master key")
    parser.add_argument("--new-key", required=True, help="New Fernet master key")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    args = parser.parse_args()

    old = SecretManager(args.old_key)
    new = SecretManager(args.new_key)
    if not old.fernet or not new.fernet:
        print("Error: one of the keys is not a valid Fernet key.")
        sys.exit(1)

    yaml_files = [
        p for p in INVENTORY_ROOT.rglob("*.yaml") if not p.name.endswith(".example.yaml")
    ]
    if not yaml_files:
        print(f"No inventory YAML files found under {INVENTORY_ROOT}")
        sys.exit(1)

    total = 0
    for path in yaml_files:
        text = path.read_text(encoding="utf-8")
        count = 0

        def _rotate(match: re.Match) -> str:
            nonlocal count
            plain = old.decrypt(match.group(0))  # Raises on wrong key
            count += 1
            return new.encrypt(plain)

        new_text = ENC_PATTERN.sub(_rotate, text)

        if count:
            total += count
            if args.dry_run:
                print(f"[dry-run] {path}: {count} secret(s) would be re-encrypted")
            else:
                path.write_text(new_text, encoding="utf-8")
                print(f"{path}: {count} secret(s) re-encrypted")

    if total == 0:
        print("No ENC(...) values found — nothing to rotate.")
    elif not args.dry_run:
        print(
            f"\nDone: {total} secret(s) rotated.\n"
            "Now update INVENTORY_MASTER_KEY in mcp_gateway/.env (and any compose env) "
            "to the NEW key and restart the gateway."
        )


if __name__ == "__main__":
    main()
