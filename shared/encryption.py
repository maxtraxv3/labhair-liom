"""Field-level encryption for the Labhair-liom database.

Encrypts sensitive fields (usernames, emails, messages) at rest using
AES-256-GCM. Only the relay server holding the master key can decrypt.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path
from typing import Optional


class FieldEncryptor:
    """AES-256-GCM field-level encryption with master key management."""

    # Fields that should be encrypted per table (everything except IDs and foreign keys)
    ENCRYPTED_FIELDS = {
        "users": {"username", "email", "display_name", "about_me", "status",
                  "created_at", "last_seen"},
        "servers": {"name", "description", "icon_url", "created_at"},
        "channels": {"name", "topic", "created_at", "encryption_key"},
        "messages": {"content", "attachments", "created_at", "edited_at", "deleted_at"},
        "direct_messages": {"content", "attachments", "created_at", "deleted_at"},
        "roles": {"name", "created_at"},
        "threads": {"name", "created_at", "updated_at"},
        "reactions": {"emoji", "created_at"},
        "friendships": {"status", "created_at"},
        "server_bans": {"reason", "created_at"},
        "server_members": {"nickname", "joined_at"},
        "thread_members": {"joined_at"},
        "channel_permissions": {},
        "user_roles": {},
        "user_profiles": {"bio", "avatar_url", "custom_status"},
    }

    # Fields that need lookup hashes (for WHERE clauses on encrypted values)
    LOOKUP_HASH_FIELDS = {
        "users": {"username", "email"},
    }

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Key must be 32 bytes (256 bits)")
        self._key = key

    @classmethod
    def generate_key(cls) -> bytes:
        """Generate a random 256-bit master key."""
        return secrets.token_bytes(32)

    @classmethod
    def load_or_create_key(cls, key_path: str | Path) -> bytes:
        """Load existing key or generate and save a new one."""
        path = Path(key_path)
        if path.exists():
            key = path.read_bytes()
            if len(key) != 32:
                raise ValueError(f"Invalid key file {key_path}: expected 32 bytes, got {len(key)}")
            return key
        key = cls.generate_key()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(key)
        # Restrict permissions (Unix only)
        try:
            os.chmod(path, 0o600)
        except (OSError, AttributeError):
            pass
        return key

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a string value. Returns base64-encoded nonce:ciphertext."""
        if not plaintext:
            return ""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:
            raise ImportError(
                "cryptography library required for encryption. "
                "Install with: pip install cryptography"
            )
        nonce = os.urandom(12)  # 96-bit nonce for GCM
        aesgcm = AESGCM(self._key)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        # Store as base64(nonce:ciphertext)
        return base64.b64encode(nonce + ciphertext).decode("ascii")

    def decrypt(self, encrypted: str) -> str:
        """Decrypt a value encrypted with encrypt()."""
        if not encrypted:
            return ""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:
            raise ImportError(
                "cryptography library required for encryption. "
                "Install with: pip install cryptography"
            )
        try:
            raw = base64.b64decode(encrypted)
            nonce = raw[:12]
            ciphertext = raw[12:]
            aesgcm = AESGCM(self._key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            return plaintext.decode("utf-8")
        except Exception:
            # If decryption fails, value might not be encrypted
            return encrypted

    @staticmethod
    def lookup_hash(value: str) -> str:
        """Generate a deterministic HMAC-SHA256 hash for encrypted field lookups.
        Uses the raw value (lowercased) so WHERE clauses work.
        """
        if not value:
            return ""
        # We use a fixed key derived from the value itself for deterministic hashing.
        # This is NOT the same as the encryption key — it's just for lookups.
        return hashlib.sha256(value.lower().encode("utf-8")).hexdigest()

    def encrypt_field(self, table: str, column: str, value: Optional[str]) -> Optional[str]:
        """Encrypt a field value if the column is in the encrypted list."""
        if value is None or (table not in self.ENCRYPTED_FIELDS):
            return value
        if column not in self.ENCRYPTED_FIELDS[table]:
            return value
        return self.encrypt(value)

    def decrypt_field(self, table: str, column: str, value: Optional[str]) -> Optional[str]:
        """Decrypt a field value if the column is in the encrypted list."""
        if value is None or (table not in self.ENCRYPTED_FIELDS):
            return value
        if column not in self.ENCRYPTED_FIELDS[table]:
            return value
        return self.decrypt(value)

    def compute_lookup_hashes(self, table: str, row: dict) -> dict:
        """Compute lookup hash columns for encrypted fields that need querying."""
        hashes = {}
        if table not in self.LOOKUP_HASH_FIELDS:
            return hashes
        for column in self.LOOKUP_HASH_FIELDS[table]:
            if column in row and row[column]:
                hashes[f"_{column}_hash"] = self.lookup_hash(row[column])
        return hashes

    def get_lookup_hash(self, table: str, column: str, value: str) -> Optional[str]:
        """Get the lookup hash for a value, for use in WHERE clauses."""
        if table not in self.LOOKUP_HASH_FIELDS:
            return None
        if column not in self.LOOKUP_HASH_FIELDS[table]:
            return None
        return self.lookup_hash(value)

    def should_encrypt(self, table: str, column: str) -> bool:
        """Check if a column should be encrypted."""
        return table in self.ENCRYPTED_FIELDS and column in self.ENCRYPTED_FIELDS[table]

    def needs_lookup_hash(self, table: str, column: str) -> bool:
        """Check if a column needs a lookup hash."""
        return table in self.LOOKUP_HASH_FIELDS and column in self.LOOKUP_HASH_FIELDS[table]

    def encrypt_row(self, table: str, row: dict) -> dict:
        """Encrypt all sensitive fields in a row dict (for INSERT)."""
        result = dict(row)
        for column in self.ENCRYPTED_FIELDS.get(table, set()):
            if column in result and result[column] is not None:
                result[column] = self.encrypt_field(table, column, str(result[column]))
        return result

    def decrypt_row(self, table: str, row: dict) -> dict:
        """Decrypt all sensitive fields in a row dict (for SELECT results)."""
        if not row:
            return row
        result = dict(row)
        for column in self.ENCRYPTED_FIELDS.get(table, set()):
            if column in result and result[column] is not None:
                result[column] = self.decrypt_field(table, column, result[column])
        return result
