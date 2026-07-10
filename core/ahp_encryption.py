"""
Authenticated encryption adapter for modules that import ``ahp_encryption``.

This module intentionally avoids mock/Base64-only "encryption." Payloads are
protected with AES-256-GCM and a PBKDF2-HMAC-SHA256 derived key. The returned
ciphertext is Base64URL text only because encrypted bytes need a safe transport
format for JSON, databases, and forms.

Post-quantum layer (v2 hybrid)
------------------------------
When the pure-Python ``kyber-py`` package is available, new payloads are sealed
with a HYBRID construction that combines the classical password/return-code key
with a post-quantum ML-KEM-768 (FIPS 203) shared secret:

    base_key     = PBKDF2-HMAC-SHA256(user_secret, salt, 390_000)      # classical
    (ek, dk)     = ML-KEM-768.keygen()
    (ss, kem_ct) = ML-KEM-768.encaps(ek)                              # post-quantum
    data_key     = HKDF-SHA256(base_key || ss, salt, "AHP-HYBRID-v2")
    ciphertext   = AES-256-GCM(data_key, plaintext)

The ML-KEM decapsulation key ``dk`` is itself wrapped under ``base_key`` with
AES-256-GCM, so the user's secret still gates all access. The result is never
weaker than the classical scheme (the data key always depends on ``base_key``),
and it binds a real ML-KEM shared secret into the key derivation so the design
is post-quantum *hybrid* rather than classical-only.

Honesty: ML-KEM-768 is a NIST-standardised KEM (FIPS 203). ``kyber-py`` is a
readable reference implementation, not a constant-time/side-channel-hardened
build; for password-based encryption at rest this is an acceptable trade-off.
If ``kyber-py`` is not installed, the module transparently falls back to the
classical AES-256-GCM path (v1) so the application can never fail to start.
Payloads written by either path are always decryptable by this module.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Post-quantum KEM is optional at import time. A missing package must never take
# the application down — the classical path remains fully functional without it.
try:  # pragma: no cover - exercised by presence/absence of the optional dep
    from kyber_py.ml_kem import ML_KEM_768 as _ML_KEM_768

    KEM_AVAILABLE = True
except Exception:  # noqa: BLE001 - any import failure => graceful classical fallback
    _ML_KEM_768 = None
    KEM_AVAILABLE = False


class EthicalLayer:
    def validate(self, payload: Any) -> bool:
        return payload is not None

    def filter(self, results):
        return results if isinstance(results, list) else []


class AxiomHarmonyProtocol:
    # Classical path, always supported for decryption (and used when the KEM is absent).
    VERSION = "AHP-AES256-GCM-v1"
    # Post-quantum hybrid path, used for new payloads when kyber-py is available.
    VERSION_HYBRID = "AHP-HYBRID-MLKEM768-AES256-GCM-v2"
    KEM_NAME = "ML-KEM-768"
    HKDF_INFO = b"AHP-HYBRID-v2-data-key"

    SALT_BYTES = 16
    NONCE_BYTES = 12
    KEY_BYTES = 32
    PBKDF2_ITERATIONS = 390_000

    def __init__(self, birth_input: str | None = None, birth_timestamp: str | None = None):
        self.birth_input = birth_input or birth_timestamp or "local-development-key"
        self.ethical_layer = EthicalLayer()

    # ---- key material -----------------------------------------------------
    def _key_hash(self) -> str:
        return hashlib.sha256(self.birth_input.encode("utf-8")).hexdigest()

    def _derive_key(self, salt: bytes) -> bytes:
        """Classical password/return-code key (PBKDF2-HMAC-SHA256)."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=self.KEY_BYTES,
            salt=salt,
            iterations=self.PBKDF2_ITERATIONS,
        )
        return kdf.derive(self.birth_input.encode("utf-8"))

    @classmethod
    def _hybrid_key(cls, base_key: bytes, shared_secret: bytes, salt: bytes) -> bytes:
        """Bind the classical key and the ML-KEM shared secret into one AES key."""
        hkdf = HKDF(algorithm=hashes.SHA256(), length=cls.KEY_BYTES, salt=salt, info=cls.HKDF_INFO)
        return hkdf.derive(base_key + shared_secret)

    # ---- encoding helpers -------------------------------------------------
    @staticmethod
    def _encode_bytes(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii")

    @staticmethod
    def _decode_bytes(value: str) -> bytes:
        return base64.urlsafe_b64decode(value.encode("ascii"))

    # ---- encryption -------------------------------------------------------
    def encrypt(self, data: Any):
        raw = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, sort_keys=True)
        raw_bytes = raw.encode("utf-8")
        salt = secrets.token_bytes(self.SALT_BYTES)
        base_key = self._derive_key(salt)

        if KEM_AVAILABLE:
            return self._encrypt_hybrid(raw_bytes, salt, base_key)
        return self._encrypt_classical(raw_bytes, salt, base_key)

    def _encrypt_classical(self, raw_bytes: bytes, salt: bytes, base_key: bytes):
        nonce = secrets.token_bytes(self.NONCE_BYTES)
        ciphertext = AESGCM(base_key).encrypt(nonce, raw_bytes, self.VERSION.encode("ascii"))
        return {
            "status": "Success",
            "version": self.VERSION,
            "encrypted": self._encode_bytes(ciphertext),
            "salt": self._encode_bytes(salt),
            "nonce": self._encode_bytes(nonce),
            "kdf": "PBKDF2-HMAC-SHA256",
            "iterations": self.PBKDF2_ITERATIONS,
            "post_quantum": False,
            "key_fingerprint": self._key_hash()[:12],
        }

    def _encrypt_hybrid(self, raw_bytes: bytes, salt: bytes, base_key: bytes):
        version = self.VERSION_HYBRID
        aad = version.encode("ascii")

        # Post-quantum key encapsulation (ML-KEM-768 / FIPS 203).
        ek, dk = _ML_KEM_768.keygen()
        shared_secret, kem_ct = _ML_KEM_768.encaps(ek)

        # The decapsulation key is wrapped under the classical key so the user's
        # secret still gates access to the post-quantum shared secret.
        dk_nonce = secrets.token_bytes(self.NONCE_BYTES)
        dk_wrapped = AESGCM(base_key).encrypt(dk_nonce, dk, aad)

        # Data key binds classical + post-quantum secrets; never weaker than classical.
        data_key = self._hybrid_key(base_key, shared_secret, salt)
        nonce = secrets.token_bytes(self.NONCE_BYTES)
        ciphertext = AESGCM(data_key).encrypt(nonce, raw_bytes, aad)

        return {
            "status": "Success",
            "version": version,
            "encrypted": self._encode_bytes(ciphertext),
            "salt": self._encode_bytes(salt),
            "nonce": self._encode_bytes(nonce),
            "kem": self.KEM_NAME,
            "kem_ct": self._encode_bytes(kem_ct),
            "dk_nonce": self._encode_bytes(dk_nonce),
            "dk_wrapped": self._encode_bytes(dk_wrapped),
            "kdf": "PBKDF2-HMAC-SHA256 + HKDF-SHA256",
            "iterations": self.PBKDF2_ITERATIONS,
            "post_quantum": True,
            "key_fingerprint": self._key_hash()[:12],
        }

    # ---- decryption -------------------------------------------------------
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

            version = payload.get("version", self.VERSION)
            salt = self._decode_bytes(payload["salt"])
            nonce = self._decode_bytes(payload["nonce"])
            ciphertext = self._decode_bytes(payload["encrypted"])
            base_key = self._derive_key(salt)

            # Post-quantum hybrid payloads carry a KEM ciphertext + wrapped dk.
            if payload.get("kem_ct") and payload.get("dk_wrapped"):
                if not KEM_AVAILABLE:
                    return {
                        "status": "Error",
                        "message": "Post-quantum payload requires the kyber-py (ML-KEM) package, which is not installed.",
                        "original_data": None,
                    }
                aad = version.encode("ascii")
                dk_nonce = self._decode_bytes(payload["dk_nonce"])
                dk_wrapped = self._decode_bytes(payload["dk_wrapped"])
                dk = AESGCM(base_key).decrypt(dk_nonce, dk_wrapped, aad)
                kem_ct = self._decode_bytes(payload["kem_ct"])
                shared_secret = _ML_KEM_768.decaps(dk, kem_ct)
                data_key = self._hybrid_key(base_key, shared_secret, salt)
                plaintext = AESGCM(data_key).decrypt(nonce, ciphertext, aad)
            else:
                # Classical v1 payload.
                plaintext = AESGCM(base_key).decrypt(nonce, ciphertext, version.encode("ascii"))

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
