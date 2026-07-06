#!/usr/bin/env python
"""Manage encrypted secrets in inventory files.

Usage:
    # 1. Generate a new master key
    uv run python scripts/encrypt_secret.py --generate

    # 2. Encrypt a single secret (requires INVENTORY_MASTER_KEY env var or --key)
    uv run python scripts/encrypt_secret.py "my-super-secret-password"

    # 3. Batch encrypt from CSV (uses the 'token' column, or the first column)
    uv run python scripts/encrypt_secret.py --batch input.csv --output output.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from gateway.inventory.secrets import SecretManager  # noqa: E402


def process_batch(manager: SecretManager, input_path: str, output_path: str):
    """Read tokens from input_path and write encrypted tokens to output_path."""
    if not os.path.exists(input_path):
        print(f"Error: Input file '{input_path}' not found.")
        sys.exit(1)

    print(f"Processing batch from: {input_path}")

    processed_rows = []
    headers = []

    with open(input_path, mode='r', newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        try:
            headers = next(reader)
        except StopIteration:
            print("Error: Empty CSV file.")
            sys.exit(1)

        # Determine which column contains the token
        token_index = 0
        if "token" in [h.lower() for h in headers]:
            token_index = [h.lower() for h in headers].index("token")

        output_headers = headers + ["encrypted_token"]

        row_count = 0
        for row in reader:
            if not row:
                continue

            # Pad rows that are missing columns
            while len(row) <= token_index:
                row.append("")

            token = row[token_index]
            if token:
                encrypted = manager.encrypt(token)
                row.append(encrypted)
            else:
                row.append("")

            processed_rows.append(row)
            row_count += 1

    with open(output_path, mode='w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(output_headers)
        writer.writerows(processed_rows)

    print(f"Success! Processed {row_count} rows.")
    print(f"Output saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Inventory Encryption Tool")
    parser.add_argument("--generate", action="store_true", help="Generate a new master key")
    parser.add_argument("--key", help="Master key (overrides INVENTORY_MASTER_KEY)")
    parser.add_argument("--batch", help="Path to input CSV file for batch processing")
    parser.add_argument("--output", default="encrypted_tokens.csv", help="Output CSV path")
    parser.add_argument("secret", nargs="?", help="The string to encrypt (single mode)")

    args = parser.parse_args()

    if args.generate:
        key = Fernet.generate_key().decode()
        print(f"\nGenerated Master Key:\n{key}\n")
        print("Add this to your .env file:\nINVENTORY_MASTER_KEY=" + key)
        return

    master_key = args.key or os.getenv("INVENTORY_MASTER_KEY")
    if not master_key:
        print("Error: INVENTORY_MASTER_KEY not found. Generate one first with --generate.")
        sys.exit(1)

    try:
        manager = SecretManager(master_key)

        if args.batch:
            process_batch(manager, args.batch, args.output)
            return

        if args.secret:
            encrypted = manager.encrypt(args.secret)
            print(f"\nEncrypted Value:\n{encrypted}\n")
            print("Paste this into your YAML inventory file.")
            return

        print("Error: You must provide a secret to encrypt, use --batch, or use --generate.")
        sys.exit(1)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
