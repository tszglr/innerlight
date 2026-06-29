"""
Authenticated encryption adapter for modules that import ``ahp_encryption``.

This module intentionally avoids mock/Base64-only "encryption." Payloads are
protected with AES-256-GCM and a PBKDF2-HMAC-SHA256 derived key. The returned
ciphertext is Base64URL text only because encrypted bytes need a safe transport
format for JSON, databases, and forms.

Note: AES-256-GCM is strong modern authenticated encryption, but it is not
post-quantum cryptography. A true quantum-resistant design needs a reviewed KEM
such as ML-KEM/Kyber for key exchange plus authenticated symmetric encryption.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class EthicalLayer:
    def validate(self, payload: Any) -> bool:
        return payload is not None

    def filter(self, results):
        return results if isinstance(results, list) else []


class AxiomHarmonyProtocol:
    VERSION = "AHP-AES256-GCM-v1"
    SALT_BYTES = 16
    NONCE_BYTES = 12
    KEY_BYTES = 32
    PBKDF2_ITERATIONS = 390_000

    def __init__(self, birth_input: str | None = None, birth_timestamp: str | None = None):
        self.birth_input = birth_input or birth_timestamp or "local-development-key"
        self.ethical_layer = EthicalLayer()

    def _key_hash(self) -> str:
        return hashlib.sha256(self.birth_input.encode("utf-8")).hexdigest()

    def _derive_key(self, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=self.KEY_BYTES,
            salt=salt,
            iterations=self.PBKDF2_ITERATIONS,
        )
        return kdf.derive(self.birth_input.encode("utf-8"))

    @staticmethod
    def _encode_bytes(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii")

    @staticmethod
    def _decode_bytes(value: str) -> bytes:
        return base64.urlsafe_b64decode(value.encode("ascii"))

    def encrypt(self, data: Any):
        raw = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, sort_keys=True)
        salt = secrets.token_bytes(self.SALT_BYTES)
        nonce = secrets.token_bytes(self.NONCE_BYTES)
        key = self._derive_key(salt)
        ciphertext = AESGCM(key).encrypt(nonce, raw.encode("utf-8"), self.VERSION.encode("ascii"))

        return {
            "status": "Success",
            "version": self.VERSION,
            "encrypted": self._encode_bytes(ciphertext),
            "salt": self._encode_bytes(salt),
            "nonce": self._encode_bytes(nonce),
            "kdf": "PBKDF2-HMAC-SHA256",
            "iterations": self.PBKDF2_ITERATIONS,
            "key_fingerprint": self._key_hash()[:12],
        }

    def decrypt(self, encrypted_data: str | dict):
        try:
            if isinstance(encrypted_data, dict):
                payload = encrypted_data
            else:
                payload = json.loads(encrypted_data) if encrypted_data.strip().startswith("{") else {
                    "encrypted": encrypted_data,
                    "salt": None,
                    "nonce": None,
                    "version": self.VERSION,
                }

            if not payload.get("salt") or not payload.get("nonce"):
                return {
                    "status": "Error",
                    "message": "Encrypted payload is missing AES-GCM salt/nonce metadata.",
                    "original_data": None,
                }

            salt = self._decode_bytes(payload["salt"])
            nonce = self._decode_bytes(payload["nonce"])
            ciphertext = self._decode_bytes(payload["encrypted"])
            key = self._derive_key(salt)
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, payload.get("version", self.VERSION).encode("ascii"))
            decoded = plaintext.decode("utf-8")

            try:
                original_data = json.loads(decoded)
            except json.JSONDecodeError:
                original_data = decoded

            return {"status": "Success", "original_data": original_data}
        except Exception as exc:
            return {"status": "Error", "message": str(exc), "original_data": None}

    def encrypt_records(self, records: dict):
        return {key: self.encrypt(value) for key, value in records.items()}

    def decrypt_records(self, records: dict):
        return {key: self.decrypt(value).get("original_data") for key, value in records.items()}
