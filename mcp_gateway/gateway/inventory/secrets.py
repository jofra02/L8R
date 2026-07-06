"""Fernet-based encryption for inventory secrets.

Secrets are stored as ``ENC(<ciphertext>)`` in the inventory YAML files and
decrypted in memory with the key from ``INVENTORY_MASTER_KEY``.
"""

import logging
import os

from cryptography.fernet import Fernet

log = logging.getLogger("gateway.secrets")


class SecretManager:
    """Encrypts/decrypts ``ENC(...)`` wrapped values."""

    PREFIX = "ENC("
    SUFFIX = ")"

    def __init__(self, master_key: str | None = None):
        if not master_key:
            master_key = os.getenv("INVENTORY_MASTER_KEY")

        if not master_key:
            # Without a key only plain-text secrets work; encrypted values are
            # passed through untouched (auth will fail downstream, which is the
            # correct signal).
            self.fernet = None
            log.debug("INVENTORY_MASTER_KEY not set. Encryption features disabled.")
        else:
            try:
                self.fernet = Fernet(master_key)
            except Exception as e:
                log.error(f"Invalid master key format: {e}")
                self.fernet = None

    def encrypt(self, secret: str) -> str:
        """Encrypt a plain-text string, returning ``ENC(<ciphertext>)``."""
        if not self.fernet:
            raise ValueError("Cannot encrypt: INVENTORY_MASTER_KEY not set.")

        token = self.fernet.encrypt(secret.encode()).decode()
        return f"{self.PREFIX}{token}{self.SUFFIX}"

    def decrypt(self, encrypted_value: str) -> str:
        """Decrypt an ``ENC(...)`` string."""
        if not self.fernet:
            log.warning("Attempted to decrypt secret without INVENTORY_MASTER_KEY.")
            return encrypted_value

        if encrypted_value.startswith(self.PREFIX) and encrypted_value.endswith(self.SUFFIX):
            ciphertext = encrypted_value[len(self.PREFIX):-len(self.SUFFIX)]
        else:
            return encrypted_value  # Not encrypted

        try:
            return self.fernet.decrypt(ciphertext.encode()).decode()
        except Exception as e:
            log.error(f"Decryption failed: {e}")
            raise ValueError("Decryption failed. Check your INVENTORY_MASTER_KEY.") from e

    def is_encrypted(self, value: str) -> bool:
        return isinstance(value, str) and value.startswith(self.PREFIX) and value.endswith(self.SUFFIX)
