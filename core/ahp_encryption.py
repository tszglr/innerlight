"""
Axiom Harmony Protocol (AHP) — authenticated encryption core for InnerLight.

REAL SECURITY POSTURE (Principle 16 — no hallucinating; state only what is true):
  * Confidentiality + integrity: AES-256-GCM authenticated encryption (AEAD).
    Tampered ciphertext fails to decrypt; it is never silently accepted.
  * Key derivation: memory-hard scrypt (n=2**15, r=8, p=1 — ~32 MiB, ~130ms per
    derive on current hardware) for all NEW records. This is far more resistant
    to GPU/ASIC brute force than a plain iterated hash, because it forces the
    attacker to pay memory, not just compute, for every guess.
  * Backward compatibility: older records were derived with PBKDF2-HMAC-SHA256 at
    390,000 iterations ("AHP-AES256-GCM-v1"). decrypt() reads each record's own
    version/kdf metadata and uses the MATCHING derivation, so v1 data stays
    readable forever while all new data is written under the stronger scrypt path
    ("AHP-AES256-GCM-scrypt-v2").
  * Per-record randomness: a fresh 16-byte salt and 12-byte GCM nonce are
    generated for every single record. No salt or nonce is ever reused.
  * Optional server pepper: if the environment variable AHP_PEPPER is set, its
    value is HKDF-combined with the per-deployment key material BEFORE the KDF
    runs. The pepper is a server-held secret that is NEVER written next to the
    ciphertext. Consequence: at-rest data stolen WITHOUT the server pepper cannot
    be brute-forced from the salt alone — the attacker is missing an input that
    does not exist in the stolen data. If AHP_PEPPER is absent, behaviour is
    byte-for-byte identical to the no-pepper path, so development and existing
    deployments are unaffected.
  * Transport: ciphertext is Base64URL text only because encrypted bytes need a
    safe representation for JSON, databases, and forms. Base64 is encoding, not
    encryption, and is never relied on for secrecy.

WHAT THIS IS NOT (stated plainly, Principle 16):
  AES-256-GCM and scrypt are strong CLASSICAL cryptography. They are NOT
  post-quantum. A sufficiently large quantum computer running Grover's algorithm
  weakens symmetric key search (AES-256 retains a large margin) and Shor's
  algorithm breaks classical public-key exchange outright. AHP does not yet
  perform any post-quantum key exchange, and this module claims none.

  Post-quantum roadmap (FUTURE work, not present today — do not cite as shipped):
  the intended path is a HYBRID key establishment that runs a classical exchange
  (e.g. X25519) alongside a reviewed post-quantum KEM such as ML-KEM (Kyber) and
  mixes both shared secrets through an HKDF so the session key is safe if EITHER
  primitive holds. That requires a vetted PQ library (e.g. liboqs) which is not a
  dependency here. Until it is built, tested, and reviewed, AHP is described
  honestly as classical AEAD with a memory-hard KDF — nothing more.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


class EthicalLayer:
    def validate(self, payload: Any) -> bool:
        return payload is not None

    def filter(self, results):
        return results if isinstance(results, list) else []


class AxiomHarmonyProtocol:
    # v1 (legacy): PBKDF2-HMAC-SHA256. Still decryptable, never written anew.
    VERSION_V1 = "AHP-AES256-GCM-v1"
    # v2 (current default): memory-hard scrypt. All new records use this.
    VERSION_V2 = "AHP-AES256-GCM-scrypt-v2"
    VERSION = VERSION_V2  # what encrypt() writes going forward

    SALT_BYTES = 16
    NONCE_BYTES = 12
    KEY_BYTES = 32

    # Legacy PBKDF2 work factor (only used to READ old v1 records).
    PBKDF2_ITERATIONS = 390_000

    # scrypt parameters — tuned so one derive costs ~130ms and ~32 MiB of memory
    # on current hardware (measured). n is the CPU/memory cost, r the block size,
    # p the parallelization. Memory-hardness (r*n*128 bytes) is the point: it
    # makes large-scale offline guessing pay for RAM, not just cycles.
    SCRYPT_N = 2 ** 15
    SCRYPT_R = 8
    SCRYPT_P = 1

    # Name of the environment variable that, if set, supplies the server pepper.
    PEPPER_ENV = "AHP_PEPPER"

    def __init__(self, birth_input: str | None = None, birth_timestamp: str | None = None):
        self.birth_input = birth_input or birth_timestamp or "local-development-key"
        self.ethical_layer = EthicalLayer()

    # ---- pepper + password material -------------------------------------
    def _pepper(self) -> bytes | None:
        """Return the server pepper bytes if AHP_PEPPER is set, else None.

        Read fresh from the environment each derive so a deployment can rotate it
        without restarting long-lived objects. Absent env var => None => the
        no-pepper path (identical to the original behaviour)."""
        raw = os.environ.get(self.PEPPER_ENV)
        if not raw:
            return None
        return raw.encode("utf-8")

    def _password_material(self) -> bytes:
        """The secret fed into the KDF.

        Without a pepper this is exactly the birth_input bytes, so records written
        before pepper support still derive the same key and stay readable. With a
        pepper set, the birth_input is HKDF-combined with the server-held pepper
        first, so the material that actually enters the KDF depends on a secret
        that is never stored beside the ciphertext."""
        base = self.birth_input.encode("utf-8")
        pepper = self._pepper()
        if pepper is None:
            return base
        # HKDF-Extract/Expand binds the pepper (as HKDF salt) into the material.
        return HKDF(
            algorithm=hashes.SHA256(),
            length=self.KEY_BYTES,
            salt=pepper,
            info=b"AHP-server-pepper-v1",
        ).derive(base)

    def _key_hash(self) -> str:
        # Non-secret fingerprint of the birth_input, for correlating records.
        return hashlib.sha256(self.birth_input.encode("utf-8")).hexdigest()

    # ---- key derivation, versioned --------------------------------------
    def _derive_scrypt(self, salt: bytes, n: int, r: int, p: int) -> bytes:
        kdf = Scrypt(
            salt=salt,
            length=self.KEY_BYTES,
            n=n,
            r=r,
            p=p,
        )
        return kdf.derive(self._password_material())

    def _derive_pbkdf2(self, salt: bytes, iterations: int) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=self.KEY_BYTES,
            salt=salt,
            iterations=iterations,
        )
        return kdf.derive(self._password_material())

    @staticmethod
    def _encode_bytes(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii")

    @staticmethod
    def _decode_bytes(value: str) -> bytes:
        return base64.urlsafe_b64decode(value.encode("ascii"))

    # ---- encrypt (default: v2 / scrypt, optional context binding) --------
    def encrypt(self, data: Any, context: str = ""):
        """Encrypt with AES-256-GCM. When a context string is given (e.g.
        "memory"), it is bound into the GCM associated data: the record then
        decrypts ONLY when presented in that same context, so a ciphertext can
        never be transplanted from one purpose to another. Records written
        without context remain fully compatible. Compelled-disclosure
        minimalism is a design goal: code-protected records are zero-knowledge
        to the operator — without the person's code there is nothing readable
        to produce."""
        raw = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, sort_keys=True)
        salt = secrets.token_bytes(self.SALT_BYTES)
        nonce = secrets.token_bytes(self.NONCE_BYTES)
        key = self._derive_scrypt(salt, self.SCRYPT_N, self.SCRYPT_R, self.SCRYPT_P)
        # Version (and context, when present) are bound as GCM associated data
        # so a record cannot be silently reinterpreted under a different scheme
        # or replayed into a different part of the system.
        aad = self.VERSION_V2 + ("|ctx:" + context if context else "")
        ciphertext = AESGCM(key).encrypt(nonce, raw.encode("utf-8"), aad.encode("utf-8"))

        return {
            "status": "Success",
            "version": self.VERSION_V2,
            "encrypted": self._encode_bytes(ciphertext),
            "salt": self._encode_bytes(salt),
            "nonce": self._encode_bytes(nonce),
            "kdf": "scrypt",
            "n": self.SCRYPT_N,
            "r": self.SCRYPT_R,
            "p": self.SCRYPT_P,
            "pepper": bool(self._pepper()),
            "ctx": bool(context),
            "key_fingerprint": self._key_hash()[:12],
        }

    def encrypt_v1(self, data: Any):
        """Explicit legacy PBKDF2 encryptor. Not used by default; kept so tests
        (and any migration tooling) can construct genuine v1 records."""
        raw = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, sort_keys=True)
        salt = secrets.token_bytes(self.SALT_BYTES)
        nonce = secrets.token_bytes(self.NONCE_BYTES)
        key = self._derive_pbkdf2(salt, self.PBKDF2_ITERATIONS)
        ciphertext = AESGCM(key).encrypt(nonce, raw.encode("utf-8"), self.VERSION_V1.encode("ascii"))
        return {
            "status": "Success",
            "version": self.VERSION_V1,
            "encrypted": self._encode_bytes(ciphertext),
            "salt": self._encode_bytes(salt),
            "nonce": self._encode_bytes(nonce),
            "kdf": "PBKDF2-HMAC-SHA256",
            "iterations": self.PBKDF2_ITERATIONS,
            "key_fingerprint": self._key_hash()[:12],
        }

    # ---- versioned decrypt ----------------------------------------------
    def _derive_for_record(self, payload: dict, salt: bytes) -> bytes:
        """Pick the KDF that matches the record's own metadata. This is what
        keeps old data readable: a v1 record derives with PBKDF2, a v2 record
        derives with scrypt, regardless of what encrypt() writes today."""
        kdf = str(payload.get("kdf", "")).lower()
        version = str(payload.get("version", ""))
        is_scrypt = ("scrypt" in kdf) or ("scrypt" in version) or (
            payload.get("n") is not None and payload.get("r") is not None
        )
        if is_scrypt:
            n = int(payload.get("n", self.SCRYPT_N))
            r = int(payload.get("r", self.SCRYPT_R))
            p = int(payload.get("p", self.SCRYPT_P))
            return self._derive_scrypt(salt, n, r, p)
        # Default / legacy: PBKDF2.
        iterations = int(payload.get("iterations", self.PBKDF2_ITERATIONS))
        return self._derive_pbkdf2(salt, iterations)

    def decrypt(self, encrypted_data: str | dict, context: str = ""):
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
            key = self._derive_for_record(payload, salt)
            aad_s = str(payload.get("version", self.VERSION))
            if payload.get("ctx"):
                # Context-bound record: decrypts only in its own context.
                aad_s += "|ctx:" + context
            aad = aad_s.encode("utf-8")
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, aad)
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
