"""Ed25519 signatures over audit pack manifests.

A hash chain alone proves only internal consistency: anyone could rebuild a fresh chain
and manifest. The lender signs each manifest, and a verifier who holds the lender's
public key (published, or obtained from the lender) can prove the pack came unaltered
from the lender's system.
"""

import base64
import hashlib
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from ledger_lens.shared.config import Backend, Settings


class Signer(Protocol):
    def sign(self, data: bytes) -> bytes: ...

    def public_key_pem(self) -> bytes: ...


def fingerprint(public_key_pem: bytes) -> str:
    """Short, stable identifier of a public key, shown next to every signature."""
    return "ed25519:" + hashlib.sha256(public_key_pem.strip()).hexdigest()[:16]


class LocalKeySigner:
    """Key kept in a PEM file, created on first use. For development only."""

    def __init__(self, key_path: Path) -> None:
        if not key_path.exists():
            key_path.parent.mkdir(parents=True, exist_ok=True)
            pem = Ed25519PrivateKey.generate().private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
            key_path.write_bytes(pem)
            key_path.chmod(0o600)
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError(f"{key_path} is not an Ed25519 private key")
        self._key = key

    def sign(self, data: bytes) -> bytes:
        return self._key.sign(data)

    def public_key_pem(self) -> bytes:
        return self._key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )


class KmsSigner:
    """Cloud KMS key (EC_SIGN_ED25519); the private key never leaves KMS."""

    def __init__(self, key_version: str) -> None:
        from google.cloud import kms_v1

        self._client = kms_v1.KeyManagementServiceClient()
        self._name = key_version

    def sign(self, data: bytes) -> bytes:
        # Ed25519 signs the message itself, so `data` (not a digest) goes in the request.
        response = self._client.asymmetric_sign(request={"name": self._name, "data": data})
        return bytes(response.signature)

    def public_key_pem(self) -> bytes:
        return str(self._client.get_public_key(name=self._name).pem).encode()


def verify_signature(public_key_pem: bytes, data: bytes, signature_b64: str) -> bool:
    key = serialization.load_pem_public_key(public_key_pem)
    if not isinstance(key, Ed25519PublicKey):
        return False
    try:
        key.verify(base64.b64decode(signature_b64), data)
    except (InvalidSignature, ValueError):
        return False
    return True


def build_signer(settings: Settings) -> Signer:
    """KMS when configured. A cloud deployment without it is a config error: a local key
    on an ephemeral container disk would be lost, leaving signed packs unverifiable."""
    if settings.audit_kms_key:
        return KmsSigner(settings.audit_kms_key)
    if settings.storage_backend is Backend.GCP:
        raise ValueError("LL_AUDIT_KMS_KEY is required when storage is gcp")
    return LocalKeySigner(settings.data_dir / "keys" / "audit-signing-ed25519.pem")
